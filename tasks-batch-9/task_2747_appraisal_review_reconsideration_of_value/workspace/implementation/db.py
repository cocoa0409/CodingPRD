"""In-memory data store and the logical UTC clock.

Storage is process-local Python dictionaries keyed by id.  Nothing is
persisted and nothing is seeded: every collection below starts empty on
every boot and is only ever populated through the declared endpoints.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- collections
loan_files = {}
appraisers = {}
amcs = {}
panel_memberships = {}
appraisals = {}
comparables = {}
rule_checks = {}
bias_flags = {}
communications = {}
desk_reviews = {}
escalation_orders = {}
rov_requests = {}
rov_evidence = {}
dispute_cases = {}
value_revisions = {}

ALL_COLLECTIONS = (
    loan_files, appraisers, amcs, panel_memberships, appraisals, comparables,
    rule_checks, bias_flags, communications, desk_reviews, escalation_orders,
    rov_requests, rov_evidence, dispute_cases, value_revisions,
)

_seq_counter = itertools.count(1)

# ------------------------------------------------------------- logical clock
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def now():
    """The logical UTC clock.  Never falls back to wall-clock time."""
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def reset():
    for coll in ALL_COLLECTIONS:
        coll.clear()
    _clock["now"] = CLOCK_EPOCH


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


# --------------------------------------------------------------- record utils
def make_record(fields, versioned=True):
    """Build a record dict.  ``versioned`` records carry the full quartet;
    append-only event records carry only ``id`` and ``created_at``."""
    stamp = now()
    rec = {"id": new_id(), "created_at": stamp}
    rec.update(fields)
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    if "updated_at" in rec:
        rec["updated_at"] = now()


def bump(rec):
    touch(rec)
    if "version" in rec:
        rec["version"] = rec["version"] + 1


def ordered(collection, predicate=None):
    """All records in created_at ascending order.  Ids never participate in
    ordering; insertion order breaks ties."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def hours_after(dt, hours):
    return dt + timedelta(hours=hours)
