"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

facilities = {}
units = {}
stocks = {}
par_levels = {}
cart_runs = {}
manifests = {}
invoices = {}
complaints = {}
surges = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
