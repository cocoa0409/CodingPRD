"""In-memory data store. Fresh on every process boot; nothing is seeded."""
import itertools
import uuid

# Entity collections, keyed by id.
programs = {}
policies = {}
providers = {}
cases = {}
reviews = {}
queries = {}
responses = {}
reconciliations = {}
targets = {}
education_events = {}
snapshots = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)
