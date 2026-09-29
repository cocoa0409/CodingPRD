"""In-memory data store, logical clock and record helpers.

Storage is process-local only: every fresh boot starts with a completely
empty store.  Nothing is seeded, preloaded or persisted anywhere.
"""
import itertools
import uuid
from datetime import datetime, timezone

# --- logical clock (PRD 2.5): fixed default, never falls back to wall clock ---
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_state = {"clock": DEFAULT_CLOCK}
_seq = itertools.count(1)


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt.astimezone(timezone.utc)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def base_record(versioned=True):
    ts = now()
    rec = {"id": new_id(), "_seq": next_seq(), "created_at": ts}
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1


# --- collections (all keyed by id) -------------------------------------------
programs = {}
stores = {}
fixture_plans = {}
size_profiles = {}
items = {}
positions = {}
receipts = {}
runs = {}
lines = {}
promo_events = {}
transfers = {}
actions = {}
snapshots = {}
