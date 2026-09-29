"""In-memory store, logical UTC clock and shared row helpers.

Nothing here is seeded: every collection starts empty on every boot and is
filled exclusively through the declared endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 50

# --- collections -----------------------------------------------------------
product_models = {}
incidents = {}
hazard_patterns = {}
evaluations = {}
section_reports = {}
recalls = {}
retailers = {}
retailer_notifications = {}
audit_visits = {}
consumer_notices = {}
remedy_claims = {}
progress_reports = {}
penalty_cases = {}

# --- logical clock ---------------------------------------------------------
# Before any client sets it the logical clock reads exactly this instant and
# never falls back to the host wall clock.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": LOGICAL_CLOCK_DEFAULT}

_seq = {"n": 0}


def now_logical():
    return _clock["now"]


def set_logical(dt):
    _clock["now"] = dt
    return _clock["now"]


def wall_now():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 UTC instant; return None when unparseable."""
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


def hours(n):
    return timedelta(hours=n)


def rhu(value, places):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def new_row(**fields):
    # The logical clock drives every timestamp in the service, created_at and
    # updated_at included; the host wall clock is never consulted.
    stamp = now_logical()
    _seq["n"] += 1
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": _seq["n"],
    }
    row.update(fields)
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1."""
    row["updated_at"] = now_logical()
    row["version"] = row["version"] + 1
    return row


def ordered(collection, predicate=None):
    """Rows in created_at ascending order (insertion order), optionally filtered."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out
