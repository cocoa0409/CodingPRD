"""In-memory data store. Every collection starts empty on every boot; nothing is
seeded, preloaded or hardcoded. Tests build all preconditions through the API.
"""
import itertools
import uuid

import clock

stores = {}
cashiers = {}
safes = {}
sales_journals = {}
till_sessions = {}
safe_transactions = {}
deposits = {}
bank_credit_records = {}
card_settlements = {}
variance_cases = {}
change_orders = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    """Common fields: id, created_at (logical clock), updated_at, version."""
    stamp = clock.now()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "_seq": next_seq(),
    }
    if with_version:
        record["updated_at"] = stamp
        record["version"] = 1
    return record


def touch(record):
    """Mutation bookkeeping: refresh updated_at and bump version by exactly 1."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
    return record


def ordered(collection):
    """created_at ascending, with insertion sequence as the stable tie-break."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
