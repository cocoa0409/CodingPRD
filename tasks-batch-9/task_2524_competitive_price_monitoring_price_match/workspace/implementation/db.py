"""In-memory data store.

Every collection is a plain dict keyed by the server-minted UUID.  The store is
EMPTY on every boot: no entity is ever seeded, preloaded or hardcoded here.
Tests construct all state through the declared API surface.
"""
import itertools
import uuid

import clock

_seq_counter = itertools.count(1)

markets = {}
competitors = {}
products = {}
stores = {}
links = {}
observations = {}
reports = {}
rules = {}
orders = {}
policies = {}
claims = {}
batches = {}
override_logs = {}

_ALL = [markets, competitors, products, stores, links, observations, reports,
        rules, orders, policies, claims, batches, override_logs]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def new_record(with_common=True):
    """Mint a record carrying id/created_at (and updated_at/version)."""
    instant = clock.now()
    rec = {"id": new_id(), "_seq": next_seq(), "created_at": instant}
    if with_common:
        rec["updated_at"] = instant
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: bump version by exactly 1 and restamp updated_at."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = clock.now()
    return rec


def ordered(collection):
    """Rows in created_at ascending order, stable on insertion sequence."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def reset():
    for coll in _ALL:
        coll.clear()
