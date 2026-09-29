"""In-memory store, logical clock and identity/versioning helpers.

Storage is process-local only: every dict below starts empty on every boot and
nothing is ever written to disk. No entity data is seeded at import time.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from errors import ApiError

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ENTITY_COLLECTIONS = (
    "sections",
    "facilities",
    "leagues",
    "players",
    "teams",
    "roster_spots",
    "matches",
    "scorecards",
    "strikes",
    "rating_appeals",
    "grievances",
    "committee_votes",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in ENTITY_COLLECTIONS:
            setattr(self, name, {})
        self.current_utc = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def collection(self, name):
        return getattr(self, name)


db = Store()


# --------------------------------------------------------------------------
# ids / request ids
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_letters + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --------------------------------------------------------------------------
# time
# --------------------------------------------------------------------------

def iso(dt):
    """ISO-8601 UTC with exactly three fractional-second digits and Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def wall_now_iso():
    return iso(datetime.now(timezone.utc))


def now():
    """Current logical time (never falls back to wall clock)."""
    return db.current_utc


def now_iso():
    return iso(db.current_utc)


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=int(minutes))


def add_hours(dt, hours):
    return dt + timedelta(hours=int(hours))


def minutes_between(a, b):
    """Whole minutes from a to b (may be negative)."""
    return int((b - a).total_seconds() // 60)


def set_clock(target):
    if target < db.current_utc:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    db.current_utc = target


# --------------------------------------------------------------------------
# entity lifecycle
# --------------------------------------------------------------------------

def _touched():
    try:
        registry = g._touched_entities
    except (AttributeError, RuntimeError):
        registry = None
    if registry is None:
        registry = set()
        try:
            g._touched_entities = registry
        except RuntimeError:
            pass
    return registry


def insert(collection, record, versioned=True):
    stamp = now_iso()
    record["created_at"] = stamp
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    getattr(db, collection)[record["id"]] = record
    _touched().add(record["id"])
    return record


def touch(record):
    """Bump updated_at/version at most once per request for this record."""
    if record is None:
        return record
    if "version" not in record:
        return record
    registry = _touched()
    if record["id"] in registry:
        return record
    registry.add(record["id"])
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1
    return record


def sorted_rows(rows):
    """Default list ordering: created_at ASC, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))


def public(record, drop=None):
    out = {}
    skip = set(drop or ())
    skip.add("_seq")
    for key, value in record.items():
        if key in skip or key.startswith("_"):
            continue
        out[key] = value
    return out
