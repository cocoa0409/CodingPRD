"""In-memory data store, logical clock, id/sequence generation, serialization.

All state lives in module-level dicts that are re-created fresh on every process
start. The store is NEVER seeded: tests build every entity through the API.
"""
import threading
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Global request lock — serialize mutations so cascades settle atomically.
# ---------------------------------------------------------------------------
LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Entity stores (id -> record dict). Empty on boot.
# ---------------------------------------------------------------------------
applicants = {}
members = {}
preference_claims = {}
waitlists = {}
waitlist_entries = {}
units = {}
offers = {}
tenancies = {}
certifications = {}
interim_changes = {}
grievances = {}

# ---------------------------------------------------------------------------
# Logical clock. Startup default is 2026-03-01T00:00:00Z; never wall-clock time
# until explicitly set.
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


# ---------------------------------------------------------------------------
# Monotonic insertion sequence — deterministic tiebreak for equal timestamps.
# ---------------------------------------------------------------------------
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


def _wall_now():
    return datetime.now(timezone.utc)


def create(store, **fields):
    """Create a record with common system fields and insert it into `store`."""
    rec = {
        "id": new_id(),
        "created_at": _wall_now(),
        "updated_at": _wall_now(),
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    store[rec["id"]] = rec
    return rec


def bump(rec):
    """Force a version increment + updated_at refresh (used where the spec
    mandates a version bump even if no visible field value changes)."""
    rec["version"] += 1
    rec["updated_at"] = _wall_now()


def touch(rec, **changes):
    """Apply field changes; if anything actually changed, bump version+updated_at
    exactly once. Returns True when a mutation occurred."""
    changed = False
    for k, v in changes.items():
        if rec.get(k) != v:
            rec[k] = v
            changed = True
    if changed:
        rec["version"] += 1
        rec["updated_at"] = _wall_now()
    return changed


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = _fmt_dt(v)
        else:
            out[k] = v
    return out


def sorted_by_created(records):
    """Default list ordering: created_at ASC, then insertion order."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
