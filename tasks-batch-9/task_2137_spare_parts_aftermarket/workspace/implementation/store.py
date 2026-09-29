"""In-memory data store and the logical clock.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded here; every entity is created by clients through declared endpoints.
"""
import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_lock = threading.RLock()
_seq = itertools.count(1)

# ---------------------------------------------------------------- clock ----
_clock = {"now": LOGICAL_CLOCK_DEFAULT}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def reset_clock():
    _clock["now"] = LOGICAL_CLOCK_DEFAULT


# ------------------------------------------------------------ collections --
parts = {}
equipment_models = {}
installed_units = {}
part_applicabilities = {}
dealers = {}
work_orders = {}
part_lines = {}
forecasts = {}
campaigns = {}
allocation_requests = {}
replenishment_orders = {}
return_authorizations = {}
price_rules = {}
ledger_entries = {}

_ALL = [
    parts, equipment_models, installed_units, part_applicabilities, dealers,
    work_orders, part_lines, forecasts, campaigns, allocation_requests,
    replenishment_orders, return_authorizations, price_rules, ledger_entries,
]


def reset_all():
    for coll in _ALL:
        coll.clear()
    reset_clock()


# ------------------------------------------------------------- utilities ---
def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days(n):
    return timedelta(days=n)


def new_record(entity_type, fields, common=True):
    """Create a record dict with the common resource properties applied."""
    stamp = now()
    rec = {
        "id": new_id(),
        "_type": entity_type,
        "_seq": next_seq(),
        "created_at": stamp,
    }
    if common:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and advance version by exactly 1."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def lock():
    return _lock
