"""In-memory data store.

Storage is process-local Python dicts keyed by the record's bare-UUID `id`.
Nothing is persisted and nothing is ever seeded: every store below starts
empty on each boot and is only ever populated through the declared API.
"""

import itertools
import threading
import uuid

import util

# The logical clock (PRD 2.4). Before any client sets it, it reads exactly
# this instant; the server never falls back to real time for domain rules.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

investigators = {}
organizations = {}
projects = {}
personnel = {}
disclosures = {}
items = {}
statements = {}
travel = {}
grants = {}
incidents = {}
trainings = {}
subawards = {}

_clock = {"value": DEFAULT_CLOCK}
_counter = itertools.count(1)
lock = threading.RLock()

# Records already version-bumped during the current request. A single request
# never bumps the same record twice, no matter how many recompute hops touch it.
_touched = set()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_counter)


def clock_str():
    return _clock["value"]


def clock_dt():
    return util.parse_dt(_clock["value"])


def set_clock(value):
    _clock["value"] = value


def begin_request():
    _touched.clear()


def touch(record):
    """Refresh updated_at and increment version — at most once per request."""
    if record is None:
        return
    key = id(record)
    if key in _touched:
        return
    _touched.add(key)
    record["updated_at"] = util.now_iso()
    record["version"] = record.get("version", 1) + 1


def base_record():
    stamp = util.now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }


def ordered(values):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(values, key=lambda r: (r["created_at"], r["_seq"]))
