"""In-memory data store, logical clock, shared constants, low-level helpers.

The store starts empty on every boot: no seeding, no files, no external state.
Every temporal rule evaluates against the logical clock (PRD 2.4), which starts
at exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# In-memory store (dicts keyed by id). Empty at every process boot.
# ---------------------------------------------------------------------------
DB = {
    "programs": {},
    "sites": {},
    "zones": {},
    "households": {},
    "bookings": {},
    "intake_events": {},
    "tickets": {},
    "runs": {},
    "events": {},
    "claims": {},
    "volunteers": {},
    "shifts": {},
    "notifications": {},
    "reports": {},
}

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = CLOCK_DEFAULT


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# ---------------------------------------------------------------------------
# Monotonic ids / timestamps
# ---------------------------------------------------------------------------
_seq = 0


def next_seq():
    """Global creation sequence; pinned tiebreak key for created_at ordering."""
    global _seq
    _seq += 1
    return _seq


_last_wall = None


def wall_now():
    """Strictly increasing wall-clock UTC instant (ms precision).

    created_at/updated_at use the wall clock so that creation timestamps carry
    millisecond precision and ties cannot occur (PRD 3.6 waitlist ordering).
    """
    global _last_wall
    n = datetime.now(timezone.utc)
    if _last_wall is not None and n <= _last_wall:
        n = _last_wall + timedelta(milliseconds=1)
    _last_wall = n
    return n


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Datetime formatting / parsing (ISO 8601 UTC, three fractional digits)
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Decimal helpers (round-half-up per PRD 2.8; never float math for money)
# ---------------------------------------------------------------------------
def r2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r3(x):
    return Decimal(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def r4(x):
    return Decimal(x).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def dec(v):
    """Coerce a JSON number to Decimal (exact via str for floats)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise ValueError("boolean is not a number")
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        return Decimal(str(v))
    raise ValueError("not a number")


def num_out(d):
    """Decimal -> JSON number."""
    if d is None:
        return None
    if isinstance(d, Decimal):
        return float(d)
    return d


# ---------------------------------------------------------------------------
# Measurement constants (PRD 2.8 / scaffold calculations)
# ---------------------------------------------------------------------------
EST_TONS = {
    "SMALL": Decimal("0.020"),
    "MEDIUM": Decimal("0.035"),
    "LARGE": Decimal("0.050"),
    "MIXED": Decimal("0.030"),
}
# Per-size-class cubic-yard conversion for gate intake (CLASS_CY). The PRD
# references this table by name without listing values; values are fixed here
# once and used consistently for gross/net volume, stockpile, and capacity math.
CLASS_CY = {
    "SMALL": Decimal("0.20"),
    "MEDIUM": Decimal("0.35"),
    "LARGE": Decimal("0.50"),
    "MIXED": Decimal("0.30"),
}
YIELD_CY_PER_TON = {
    "MIXED_CONIFER": Decimal("2.2"),
    "HARDWOOD": Decimal("1.8"),
    "MIXED_LOAD": Decimal("2.0"),
}

PARTICIPANT_RESERVE_PCT = Decimal("0.60")
MIN_CLAIM_CY = Decimal("0.5")
DEFAULT_PER_HOUSEHOLD_CAP_CY = Decimal("2.0")
YIELD_VARIANCE_THRESHOLD = Decimal("0.08")
STRIKE_THRESHOLD = 2
POSTURE_TICKET_THRESHOLD = 3
NO_SHOW_LIMIT = 3
GRADE_A_THRESHOLD = Decimal("0.9000")
GRADE_B_THRESHOLD = Decimal("0.7500")

SIZE_CLASSES = ("SMALL", "MEDIUM", "LARGE", "MIXED")
SOURCE_TYPES = ("RESIDENT_SELF_HAUL", "COMMERCIAL_LANDSCAPER", "CITY_CREW")
TICKET_CATEGORIES = ("DECORATIONS", "STAND_ATTACHED", "FLOCKED_TREE", "WREATH_WITH_WIRE", "OTHER")
MATERIAL_CLASSES = ("MIXED_CONIFER", "HARDWOOD", "MIXED_LOAD")
SHIFT_ROLES = ("GREETER", "TRAFFIC_CONTROL", "LOADER")
NOTIFICATION_KINDS = (
    "PROGRAM_PUBLISHED",
    "ZONE_RESCHEDULED",
    "BOOKING_AUTO_CANCELLED",
    "CLAIM_PROMOTED",
    "SITE_CLOSING",
    "MULCH_EVENT_OPENED",
)
