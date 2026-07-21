"""In-memory store, logical clock, and shared helpers.

Everything is process-local and lives only in module-level dicts, so a fresh
process (start.sh re-invocation) wipes all state. No entity is seeded at import.
"""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5). Default 2026-07-01T00:00:00Z until a Manager sets it.
# ---------------------------------------------------------------------------
_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _CLOCK


def set_clock(dt):
    global _CLOCK
    _CLOCK = dt


# ---------------------------------------------------------------------------
# Sequence counter (stable ordering tiebreaker for created_at sort).
# ---------------------------------------------------------------------------
_SEQ = 0


def next_seq():
    global _SEQ
    _SEQ += 1
    return _SEQ


# ---------------------------------------------------------------------------
# In-memory collections keyed by id.
# ---------------------------------------------------------------------------
products = {}
airlines = {}
customers = {}
registrations = {}
claims = {}
repair_orders = {}
repair_lines = {}
sales_orders = {}
sales_order_lines = {}
trade_ins = {}
special_orders = {}
recall_notices = {}
benches = {}
stations = {}


# ---------------------------------------------------------------------------
# Datetime helpers.
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO-8601 string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Add whole calendar months, preserving the time-of-day instant."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to the last valid day of the target month
    if month == 12:
        first_next = datetime(year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        first_next = datetime(year, month + 1, 1, tzinfo=dt.tzinfo)
    last_day = (first_next - timedelta(days=1)).day
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Money / points helpers.
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div_100(cents):
    return int(Decimal(cents) // Decimal(100))


def floor_dec(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Identity helpers.
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Record creation / mutation.
# ---------------------------------------------------------------------------
def create_record(collection, data, common=True):
    rec = dict(data)
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["_seq"] = next_seq()
    if common:
        rec["updated_at"] = now()
        rec["version"] = 1
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Bump version and refresh updated_at for a full-lifecycle resource."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now()


# ---------------------------------------------------------------------------
# Serialization: strip internal keys, format datetimes.
# ---------------------------------------------------------------------------
def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def sort_by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
