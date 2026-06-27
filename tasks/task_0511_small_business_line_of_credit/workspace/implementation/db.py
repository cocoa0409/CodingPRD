"""In-memory data store. Python dicts keyed by id. No persistence, no seeding.

Every entity is created by tests via the declared API surface. The store starts
empty on every boot.

A monotonically-increasing logical sequence (seq) is stamped on each record at
creation. It provides a deterministic creation-order tie-break for sorting and
for the FIFO/ledger orderings the spec requires (NEVER by id).
"""
import itertools
import uuid

# One dict per entity type, keyed by id.
merchants = {}
bank_feeds = {}
applications = {}
credit_lines = {}
draws = {}
remittances = {}
line_increase_requests = {}
renewal_offers = {}
statements = {}
ledger_entries = {}

_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())
