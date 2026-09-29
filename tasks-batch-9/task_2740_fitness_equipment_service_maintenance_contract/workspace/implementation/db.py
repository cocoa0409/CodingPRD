"""In-memory data store and logical service clock for FleetCare.

The store starts completely EMPTY on every boot. Nothing is seeded, preloaded
or hardcoded: all state is built by callers through the declared endpoints.
"""
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Collections (all keyed by entity id)
# ---------------------------------------------------------------------------
clubs = {}
equipment_models = {}
equipment = {}
contracts = {}
technicians = {}
assignments = {}
visits = {}
calls = {}
parts = {}
part_orders = {}
downtime_events = {}
quotes = {}

_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# Logical service clock -- the host wall clock is never consulted.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt.astimezone(timezone.utc)
    return _clock["now"]


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(now())


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_row():
    """Common system fields shared by every entity."""
    stamp = now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(row):
    """A mutation of a row: updated_at moves and version advances by one."""
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1
    return row


def apply_changes(row, changes):
    """Assign only real changes; bump the row exactly once when something moved."""
    moved = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            moved = True
    if moved:
        touch(row)
    return moved


def ordered(collection, predicate=None):
    """Rows in default order: created_at ascending (insertion order breaks ties)."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def reset():
    """Used only by tests of this module; never called at startup."""
    for coll in (clubs, equipment_models, equipment, contracts, technicians,
                 assignments, visits, calls, parts, part_orders,
                 downtime_events, quotes):
        coll.clear()
    _clock["now"] = DEFAULT_CLOCK


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)
