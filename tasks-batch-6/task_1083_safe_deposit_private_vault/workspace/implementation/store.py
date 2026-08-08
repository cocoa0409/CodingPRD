"""In-memory data store, logical clock, and low-level helpers."""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Data store: empty on every boot. Every entity is created via the API.
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "branches", "box_types", "boxes", "renters", "rentals", "invoices",
    "payments", "access_grants", "access_appointments", "access_events",
    "inventory_items", "drilling_orders", "compliance_cases",
]

DB = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence used as the stable sort key for list endpoints.
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# ---------------------------------------------------------------------------
# Logical clock. Starts at 2026-05-01T00:00:00Z and only moves when set.
# ---------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt


def clock_now_iso():
    return iso(CLOCK["now"])


def clock_now_date():
    return CLOCK["now"].date()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    return iso(datetime.now(timezone.utc))


def new_id():
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if value is None:
        return None
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Bare date, e.g. "2026-05-01"
        dt = datetime.fromisoformat(s + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_date(value):
    dt = parse_iso(value)
    return dt.date() if dt else None


def add_months(dt, months):
    month0 = dt.month - 1 + months
    year = dt.year + month0 // 12
    month = month0 % 12 + 1
    # clamp day
    import calendar
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def rhu(value):
    """Round half up to a whole integer (cents)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(value):
    return Decimal(str(value))
