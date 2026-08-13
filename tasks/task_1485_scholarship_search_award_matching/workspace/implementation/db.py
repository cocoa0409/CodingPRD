"""In-memory data store. Starts empty on every boot; no seeding (per skill contract)."""

import uuid
import threading

import clock

_lock = threading.RLock()

COLLECTIONS = [
    "students", "donors", "award_funds", "programs", "applications",
    "components", "reminders", "review_cycles", "review_scores", "awards",
    "disbursements", "adjustments", "renewal_evaluations", "thank_you_letters",
    "donor_reports",
]

store = {name: {} for name in COLLECTIONS}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def create_record(collection, fields):
    """Insert a record with common fields; returns the record dict."""
    ts = clock.now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    store[collection][rec["id"]] = rec
    return rec


def get(collection, rid):
    return store[collection].get(rid)


def all_records(collection):
    return list(store[collection].values())


def mutate(rec, **fields):
    """Apply field changes; bump version + updated_at only when something changed."""
    changed = False
    for k, v in fields.items():
        if rec.get(k) != v:
            rec[k] = v
            changed = True
    if changed:
        rec["version"] += 1
        rec["updated_at"] = clock.now_iso()
    return rec


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = clock.now_iso()
    return rec


def serialize(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def lock():
    return _lock
