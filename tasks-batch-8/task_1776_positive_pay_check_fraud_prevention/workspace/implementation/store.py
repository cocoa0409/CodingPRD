"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid

enrollments = {}
users = {}
accounts = {}
uploads = {}
checks = {}
items = {}
exceptions = {}
ach_rules = {}
fees = {}
cases = {}
sessions = {}
ops_runs = {}

# presented-item idempotency: (account_id, idempotency_key) -> (payload_hash, item_id)
item_idem = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
