"""In-memory store, logical clock, and primitive helpers.

Storage is process-local Python dicts only.  Nothing is persisted anywhere, and
NO entity data is ever seeded: every collection below starts empty on boot and
is populated exclusively by the declared API endpoints.
"""
import datetime as _dt
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

# --------------------------------------------------------------------------
# Logical clock.  Startup default is exactly 2026-08-01T00:00:00Z.  Real
# wall-clock time is NEVER consulted for business rules.
# --------------------------------------------------------------------------
CLOCK_DEFAULT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)

_state = {"clock": CLOCK_DEFAULT}


def clock_now():
    return _state["clock"]


def set_clock(value):
    _state["clock"] = value


# --------------------------------------------------------------------------
# Collections (all empty at boot)
# --------------------------------------------------------------------------
events = {}
bulletins = {}
adjusters = {}
housing_blocks = {}
deployments = {}
claims = {}
assignments = {}
advances = {}
reserve_entries = {}
vendor_firms = {}
vendor_assignments = {}
loss_estimates = {}
batches = {}

ALL_COLLECTIONS = (
    events, bulletins, adjusters, housing_blocks, deployments, claims,
    assignments, advances, reserve_entries, vendor_firms, vendor_assignments,
    loss_estimates, batches,
)

_seq = {"n": 0}


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def next_insert_seq():
    """Monotone insertion counter used to make created_at ties deterministic."""
    _seq["n"] += 1
    return _seq["n"]


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def fmt_dt(value):
    if value is None:
        return None
    v = value.astimezone(_dt.timezone.utc)
    return v.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (v.microsecond // 1000)


def parse_dt(raw):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        out = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if out.tzinfo is None:
        out = out.replace(tzinfo=_dt.timezone.utc)
    return out.astimezone(_dt.timezone.utc)


def add_days(instant, days):
    return instant + _dt.timedelta(days=int(days))


def add_hours(instant, hours):
    return instant + _dt.timedelta(hours=float(hours))


def whole_days_between(start, end):
    """Whole days from start up to but not including end (floored at 0)."""
    if end <= start:
        return 0
    return int((end - start).total_seconds() // 86400)


def hours_between(start, end):
    return money((Decimal(str((end - start).total_seconds())) / Decimal("3600")))


def date_floor(instant):
    return instant.replace(hour=0, minute=0, second=0, microsecond=0)


def night_set(start, end):
    """Whole calendar days in [start_date, end_date) as a set of date objects."""
    out = set()
    cur = date_floor(start)
    stop = date_floor(end)
    while cur < stop:
        out.add(cur.date())
        cur = cur + _dt.timedelta(days=1)
    return out


# --------------------------------------------------------------------------
# Numeric helpers.  Money is Decimal, 2dp, ROUND_HALF_UP everywhere.
# --------------------------------------------------------------------------
TWO = Decimal("0.01")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(0)
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def money(value):
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def out_money(value):
    return float(money(value))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def clamp(value, low, high):
    if value < low:
        return dec(low)
    if value > high:
        return dec(high)
    return dec(value)


# --------------------------------------------------------------------------
# Record helpers
# --------------------------------------------------------------------------
def base_record(with_common=True):
    now = clock_now()
    rec = {"id": new_id(), "created_at": now, "_seq": next_insert_seq()}
    if with_common:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation stamp: refresh updated_at and increment version by exactly 1."""
    if rec is None:
        return
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = clock_now()


def sorted_rows(rows, key="created_at"):
    return sorted(rows, key=lambda r: (r.get(key), r.get("_seq", 0)))
