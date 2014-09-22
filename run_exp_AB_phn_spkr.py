"""Runs deep learning experiments on speech dataset.

Usage:
    run_exp.py [--dataset-path=path] [--dataset-name=timit] 
    [--iterator-type=sentences] [--batch-size=100] [--nframes=13] 
    [--features=fbank] [--init-lr=0.001] [--epochs=500] 
    [--network-type=dropout_net] [--trainer-type=adadelta] 
    [--prefix-output-fname=my_prefix_42] [--debug-test] [--debug-print=0] 
    [--debug-time] [--debug-plot=0]


Options:
    -h --help                   Show this screen
    --version                   Show version
    --dataset-path=str          A valid path to the dataset
    default is timit
    --dataset-name=str          Name of the dataset (for outputs/saves)
    default is "timit"
    --iterator-type=str         "sentences" | "batch" | "dtw"
    default is "sentences"
    --batch-size=int            Batch size, used only by the batch iterator
    default is 100 (unused for "sentences" iterator type)
    --nframes=int               Number of frames to base the first layer on
    default is 13
    --features=str              "fbank" | "MFCC" (some others are not tested)
    default is "fbank"
    --init-lr=float             Initial learning rate for SGD
    default is 0.001 (that is very low intentionally)
    --epochs=int                Max number of epochs (always early stopping)
    default is 500
    --network-type=str         "dropout*" | "*" | "dropout_ab_net*"
    default is "dropout_net"
    --trainer-type=str         "SGD" | "adagrad" | "adadelta"
    default is "adadelta"
    --prefix-output-fname=str  An additional prefix to the output file name
    default is "" (empty string)
    --debug-test               Flag that activates training on the test set
    default is False, using it makes it True
    --debug-print=int          Level of debug printing. 0: nothing, 1: network
    default is 0               2: epochs/iters related
    --debug-time               Flag that activates timing epoch duration
    default is False, using it makes it True
    --debug-plot=int           Level of debug plotting, 1: costs
    default is 0               >= 2: gradients & updates
"""

import socket, docopt, cPickle, time, sys, os
import numpy
import matplotlib
matplotlib.use('Agg')
try:
    import prettyplotlib as ppl
except:
    print >> sys.stderr, "you should install prettyplotlib"
import matplotlib.pyplot as plt
import joblib
import random
from random import shuffle

from prep_timit import load_data
from dataset_iterators import DatasetSentencesIterator
from dataset_iterators import DatasetDTWIterator, DatasetBatchIteratorPhn
from dataset_iterators import DatasetDTWWrdSpkrIterator, DatasetDTReWIterator
from layers import Linear, ReLU, SigmoidLayer
from classifiers import LogisticRegression
from nnet_archs import ABNeuralNet2Outputs
from nnet_archs import DropoutABNeuralNet # TODO

DEFAULT_DATASET = '/fhgfs/bootphon/scratch/gsynnaeve/TIMIT/train_dev_test_split'
if socket.gethostname() == "syhws-MacBook-Pro.local":
    DEFAULT_DATASET = '/Users/gabrielsynnaeve/postdoc/datasets/TIMIT_train_dev_test'
elif socket.gethostname() == "TODO":  # TODO
    DEFAULT_DATASET = '/media/bigdata/TIMIT_train_dev_test'
DEBUG = False

REDTW = False
DIM_EMBEDDING = 50


def print_mean_weights_biases(params):
    for layer_ind, param in enumerate(params):
        filler = "weight"
        if layer_ind % 2:
            filler = "bias"
        print("layer %i mean %s values %f and std devs %f" % (layer_ind/2, 
            filler, numpy.mean(param.eval()), numpy.std(param.eval())))


def plot_costs(cost):
    # TODO
    pass


def rolling_avg_pgu(iteration, pgu, l):
    # (iteration * pgu + l) / (iteration + 1)
    assert len(l) == len(pgu)
    ll = len(l)/3
    params, gparams, updates = l[:ll], l[ll:-ll], l[-ll:]
    mpars, mgpars, mupds = pgu[:ll], pgu[ll:-ll], pgu[-ll:]
    ii = iteration + 1
    return [(iteration * mpars[k] + p) / ii for k, p in enumerate(params)] +\
            [(iteration * mgpars[k] + g) / ii for k, g in enumerate(gparams)] +\
            [(iteration * mupds[k] + u) / ii for k, u in enumerate(updates)]


def plot_params_gradients_updates(n, l):
    # TODO currently works only with THEANO_FLAGS="device=cpu" (not working on
    #CudaNDArrays)
    def plot_helper(li, ti, p):
        if ppl == None:
            print >> sys.stderr, "cannot plot this without prettyplotlib"
            return
        fig, ax = plt.subplots(1)
        if li % 2:
            title = "biases" + ti
            ppl.bar(ax, numpy.arange(p.shape[0]), p) # TODO with plt
        else:
            title = "weights" + ti
            ppl.pcolormesh(fig, ax, p) # TODO with plt
        plt.title(title)
        plt.savefig(title + ".png")
        #ppl.show()
        plt.close()
    ll = len(l)/3
    params, gparams, updates = l[:ll], l[ll:-ll], l[-ll:]
    if DEBUG:
        print "params"
        print params
        print "===================="
        print "gparams"  # TODO find out why not CudaNDArray here
        print gparams
        print "===================="
        print "updates"  # TODO find out why not CudaNDArray here
        print updates
    title_iter =  "_%04i" % n
    for layer_ind, param in enumerate(params):
        title = "_for_layer_" + str(layer_ind/3) + title_iter
        plot_helper(layer_ind, title, param)
    for layer_ind, gparam in enumerate(gparams):
        title = "_gradients_for_layer_" + str(layer_ind/3) + title_iter
        plot_helper(layer_ind, title, gparam)
    for layer_ind, update in enumerate(updates):
        title = "_updates_for_layer_" + str(layer_ind/3) + title_iter
        plot_helper(layer_ind, title, update)


def run(dataset_path=DEFAULT_DATASET, dataset_name='timit',
        iterator_type=DatasetDTWIterator, batch_size=100,
        nframes=13, features="fbank",
        init_lr=0.01, max_epochs=500, 
        network_type="dropout_net", trainer_type="adadelta",
        layers_types=[ReLU, ReLU, ReLU, ReLU, LogisticRegression],
        layers_sizes=[2400, 2400, 2400, 2400],
        dropout_rates=[0.2, 0.5, 0.5, 0.5, 0.5],
        recurrent_connections=[],
        prefix_fname='',
        debug_on_test_only=False,
        debug_print=0,
        debug_time=False,
        debug_plot=0):
    """
    FIXME TODO
    """

    output_file_name = dataset_name
    if prefix_fname != "":
        output_file_name = prefix_fname + "_" + dataset_name
    output_file_name += "_" + features + str(nframes)
    output_file_name += "_" + network_type + "_" + trainer_type
    output_file_name += "_emb_" + str(DIM_EMBEDDING)
    print "output file name:", output_file_name

    n_ins = None
    n_outs = None
    print "loading dataset from", dataset_path
     # TODO DO A FUNCTION
    if dataset_path[-7:] != '.joblib':
        print >> sys.stderr, "prepare your dataset with align_words.py"
        sys.exit(-1)

    ### LOADING DATA
    data_same = joblib.load(dataset_path)
    shuffle(data_same)

    has_dev_and_test_set = True
    dev_dataset_path = dataset_path[:-7].replace("train", "") + 'dev.joblib'
    test_dataset_path = dataset_path[:-7].replace("train", "") + 'test.joblib'
    dev_split_at = len(data_same)
    test_split_at = len(data_same)
    if not os.path.exists(dev_dataset_path) or not os.path.exists(test_dataset_path):
        has_dev_and_test_set = False
        dev_split_at = int(0.8 * dev_split_at)
        test_split_at = int(0.9 * test_split_at)

    n_ins = data_same[0][3].shape[1] * nframes
    n_outs = DIM_EMBEDDING

    ### TRAIN SET
    if has_dev_and_test_set:
        train_set_iterator = DatasetDTWWrdSpkrIterator(data_same, mean=None,
                std=None, nframes=nframes, batch_size=batch_size, marginf=3)
    else:
        train_set_iterator = DatasetDTWWrdSpkrIterator(
                data_same[:dev_split_at], mean=None,
                std=None, nframes=nframes, batch_size=batch_size, marginf=3)
    mean = train_set_iterator._mean
    std = train_set_iterator._std

    ### DEV SET
    if has_dev_and_test_set:
        data_same = joblib.load(dev_dataset_path)
        valid_set_iterator = DatasetDTWWrdSpkrIterator(data_same, mean=mean,
                std=std, nframes=nframes, batch_size=batch_size, marginf=3)
    else:
        valid_set_iterator = DatasetDTWWrdSpkrIterator(
                data_same[dev_split_at:test_split_at], mean=mean,
                std=std, nframes=nframes, batch_size=batch_size, marginf=3)

    ### TEST SET
    if has_dev_and_test_set:
        data_same = joblib.load(test_dataset_path)
        test_set_iterator = DatasetDTWWrdSpkrIterator(data_same, mean=mean,
                std=std, nframes=nframes, batch_size=batch_size, marginf=3)
    else:
        test_set_iterator = DatasetDTWWrdSpkrIterator(
                data_same[test_split_at:], mean=mean,
                std=std, nframes=nframes, batch_size=batch_size, marginf=3)

    assert n_ins != None
    assert n_outs != None

    # numpy random generator
    numpy_rng = numpy.random.RandomState(123)
    print '... building the model'

    # TODO the proper network type other than just dropout or not
    nnet = None
    fast_dropout = False
    if "fast_dropout" in network_type:
        fast_dropout = True
    if "dropout" in network_type:
        nnet = DropoutABNeuralNet(numpy_rng=numpy_rng, 
                n_ins=n_ins,
                layers_types=layers_types,
                layers_sizes=layers_sizes,
                n_outs=n_outs,
                loss='cos_cos2',
                rho=0.95,
                eps=1.E-6,
                max_norm=4.,
                fast_drop=fast_dropout,
                debugprint=debug_print)
    else:
        nnet = ABNeuralNet2Outputs(numpy_rng=numpy_rng, 
                n_ins=n_ins,
                layers_types=layers_types,
                layers_sizes=layers_sizes,
                n_outs=n_outs,
                loss='cos_cos2',
                rho=0.90,
                eps=1.E-6,
                max_norm=4.,
                debugprint=debug_print)
    print "Created a neural net as:",
    print str(nnet)

    # get the training, validation and testing function for the model
    print '... getting the training functions'
    print trainer_type
    train_fn = None
    if debug_plot or debug_print:
        if trainer_type == "adadelta":
            train_fn = nnet.get_adadelta_trainer(debug=True)
        elif trainer_type == "adagrad":
            train_fn = nnet.get_adagrad_trainer(debug=True)
        else:
            train_fn = nnet.get_SGD_trainer(debug=True)
    else:
        if trainer_type == "adadelta":
            train_fn = nnet.get_adadelta_trainer()
        elif trainer_type == "adagrad":
            train_fn = nnet.get_adagrad_trainer()
        else:
            train_fn = nnet.get_SGD_trainer()

    train_scoref_w = nnet.score_classif_same_diff_word_separated(train_set_iterator)
    valid_scoref_w = nnet.score_classif_same_diff_word_separated(valid_set_iterator)
    train_scoref_s = nnet.score_classif_same_diff_spkr_separated(train_set_iterator)
    valid_scoref_s = nnet.score_classif_same_diff_spkr_separated(valid_set_iterator)
    test_scoref = nnet.score_classif(test_set_iterator)
    data_iterator = train_set_iterator

    if debug_on_test_only:
        print >> sys.stderr, "NOT IMPLEMENTED"
        sys.exit(-1)
        data_iterator = test_set_iterator
        train_scoref_w = test_scoref_w
        train_scoref_s = test_scoref_s

    print '... training the model'
    # early-stopping parameters
    patience = 1000  # look as this many examples regardless TODO
    patience_increase = 2.  # wait this much longer when a new best is
                            # found
    improvement_threshold = 0.995  # a relative improvement of this much is
                                   # considered significant

    best_validation_loss = numpy.inf
    test_score = 0.
    start_time = time.clock()

    done_looping = False
    epoch = 0
    lr = init_lr
    timer = None
    if debug_plot:
        print_mean_weights_biases(nnet.params)
    #with open(output_file_name + 'epoch_0.pickle', 'wb') as f:
    #    cPickle.dump(nnet, f)

    while (epoch < max_epochs) and (not done_looping):
        if REDTW and "ab_net" in network_type and ((epoch + 1) % 20) == 0:
            print "recomputing DTW:"
            data_iterator.recompute_DTW(nnet.transform_x1())

        epoch = epoch + 1
        avg_costs = []
        avg_params_gradients_updates = []
        if debug_time:
            timer = time.time()
        for iteration, (x, y) in enumerate(data_iterator):
            avg_cost = 0.
            if "delta" in trainer_type:  # TODO remove need for this if
                avg_cost = train_fn(x[0], x[1], y[0], y[1])
            else:
                avg_cost = train_fn(x[0], x[1], y[0], y[1], lr)
            if debug_print >= 3:
                print "cost:", avg_cost[0]
            if debug_plot >= 2:
                plot_costs(avg_cost[0])
                if not len(avg_params_gradients_updates):
                    avg_params_gradients_updates = map(numpy.asarray, avg_cost[1:])
                else:
                    avg_params_gradients_updates = rolling_avg_pgu(
                            iteration, avg_params_gradients_updates,
                            map(numpy.asarray, avg_cost[1:]))
            if debug_plot >= 3:
                plot_params_gradients_updates(iteration, avg_cost[1:])
            if type(avg_cost) == list:
                avg_costs.append(avg_cost[0])
            else:
                avg_costs.append(avg_cost)
        if debug_print >= 2:
            print_mean_weights_biases(nnet.params)
        if debug_plot >= 2:
            plot_params_gradients_updates(epoch, avg_params_gradients_updates)
        if debug_time:
            print('  epoch %i took %f seconds' % (epoch, time.time() - timer))
        print('  epoch %i, avg costs %f' % \
              (epoch, numpy.mean(avg_costs)))
        tmp_train = zip(*train_scoref_w())
        print('  epoch %i, training sim same words %f, diff words %f' % \
              (epoch, numpy.mean(tmp_train[0]), numpy.mean(tmp_train[1])))
        tmp_train = zip(*train_scoref_s())
        print('  epoch %i, training sim same spkrs %f, diff spkrs %f' % \
              (epoch, numpy.mean(tmp_train[0]), numpy.mean(tmp_train[1])))
        # TODO update lr(t) = lr(0) / (1 + lr(0) * lambda * t)
        lr = numpy.float32(init_lr / (numpy.sqrt(iteration) + 1.))
        # or another scheme for learning rate decay
        #with open(output_file_name + 'epoch_' +str(epoch) + '.pickle', 'wb') as f:
        #    cPickle.dump(nnet, f)

        if debug_on_test_only:
            continue

        # we check the validation loss on every epoch
        validation_losses_w = zip(*valid_scoref_w())
        validation_losses_s = zip(*valid_scoref_s())
        this_validation_loss = 0.25*(1.-numpy.mean(validation_losses_w[0])) +\
                0.25*numpy.mean(validation_losses_w[1]) +\
                0.25*(1.-numpy.mean(validation_losses_s[0])) +\
                0.25*numpy.mean(validation_losses_s[1])

        print('  epoch %i, valid sim same words %f, diff words %f' % \
              (epoch, numpy.mean(validation_losses_w[0]), numpy.mean(validation_losses_w[1])))
        print('  epoch %i, valid sim same spkrs %f, diff spkrs %f' % \
              (epoch, numpy.mean(validation_losses_s[0]), numpy.mean(validation_losses_s[1])))
        # if we got the best validation score until now
        if this_validation_loss < best_validation_loss:
            with open(output_file_name + '.pickle', 'wb') as f:
                cPickle.dump(nnet, f)
            # improve patience if loss improvement is good enough
            if (this_validation_loss < best_validation_loss *
                improvement_threshold):
                patience = max(patience, iteration * patience_increase)
            # save best validation score and iteration number
            best_validation_loss = this_validation_loss
            # test it on the test set
            test_losses = test_scoref()
            test_score_same = numpy.mean(test_losses[0])  # TODO this is a mean of means (with different lengths)
            test_score_diff = numpy.mean(test_losses[1])  # TODO this is a mean of means (with different lengths)
            print(('  epoch %i, test sim of best model same %f diff %f') %
                  (epoch, test_score_same, test_score_diff))
        if patience <= iteration:  # TODO correct that
            done_looping = True
            break

    end_time = time.clock()
    print(('Optimization complete with best validation score of %f, '
           'with test performance %f') %
                 (best_validation_loss, test_score))
    print >> sys.stderr, ('The fine tuning code for file ' +
                          os.path.split(__file__)[1] +
                          ' ran for %.2fm' % ((end_time - start_time)
                                              / 60.))
    with open(output_file_name + '_final.pickle', 'wb') as f:
        cPickle.dump(nnet, f)

if __name__=='__main__':
    arguments = docopt.docopt(__doc__, version='run_exp version 0.1')
    dataset_path=DEFAULT_DATASET
    if arguments['--dataset-path'] != None:
        dataset_path = arguments['--dataset-path']
    dataset_name = 'timit'
    if arguments['--dataset-name'] != None:
        dataset_name = arguments['--dataset-name']
    iterator_type = DatasetSentencesIterator
    if arguments['--iterator-type'] != None:
        if "sentences" in arguments['--iterator-type']:
            iterator_type = DatasetSentencesIterator
        elif "dtw" in arguments['--iterator-type']:
            if "spkr" in arguments['--iterator-type']:
                iterator_type = DatasetDTWWrdSpkrIterator
            else:
                if REDTW:
                    iterator_type = DatasetDTReWIterator
                else:
                    iterator_type = DatasetDTWIterator
        else:
            iterator_type = DatasetBatchIteratorPhn  # TODO
    batch_size = 100
    if arguments['--batch-size'] != None:
        batch_size = int(arguments['--batch-size'])
    nframes = 13
    if arguments['--nframes'] != None:
        nframes = int(arguments['--nframes'])
    features = 'fbank'
    if arguments['--features'] != None:
        features = arguments['--features']
    init_lr = 0.01
    if arguments['--init-lr'] != None:
        init_lr = float(arguments['--init-lr'])
    max_epochs = 500
    if arguments['--epochs'] != None:
        max_epochs = int(arguments['--epochs'])
    network_type = 'dropout_net'
    if arguments['--network-type'] != None:
        network_type = arguments['--network-type']
    trainer_type = 'adadelta'
    if arguments['--trainer-type'] != None:
        trainer_type = arguments['--trainer-type']
    prefix_fname = ''
    if arguments['--prefix-output-fname'] != None:
        prefix_fname = arguments['--prefix-output-fname']
    debug_on_test_only = False
    if arguments['--debug-test']:
        debug_on_test_only = True
    debug_print = 0
    if arguments['--debug-print']:
        debug_print = int(arguments['--debug-print'])
    debug_time = False
    if arguments['--debug-time']:
        debug_time = True
    debug_plot = 0
    if arguments['--debug-plot']:
        debug_plot = int(arguments['--debug-plot'])

    run(dataset_path=dataset_path, dataset_name=dataset_name,
        iterator_type=iterator_type, batch_size=batch_size,
        nframes=nframes, features=features,
        init_lr=init_lr, max_epochs=max_epochs, 
        network_type=network_type, trainer_type=trainer_type,
        #layers_types=[ReLU, ReLU, ReLU, ReLU],
        #layers_sizes=[2000, 2000, 2000],
        #dropout_rates=[0.2, 0.5, 0.5, 0.5],
        layers_types=[ReLU, ReLU],
        #layers_types=[SigmoidLayer, SigmoidLayer],
        layers_sizes=[200],
        recurrent_connections=[],  # TODO in opts
        prefix_fname=prefix_fname,
        debug_on_test_only=debug_on_test_only,
        debug_print=debug_print,
        debug_time=debug_time,
        debug_plot=debug_plot)