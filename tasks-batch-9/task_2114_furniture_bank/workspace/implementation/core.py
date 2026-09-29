"""Core primitives: the logical clock, id minting, timestamp formatting,
rounding helpers and the global constants referenced across the domain.

PRD 2.4 (common resource properties), 2.6 (logical clock), 2.7 (precision).
"""

import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Logical clock (PRD 2.6) - before any operator sets it the clock reads
# exactly 2026-08-01T00:00:00Z and the server never falls back to wall time
# for business purposes.
# --------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self._now = CLOCK_DEFAULT_UTC

    def now(self):
        return self._now

    def set(self, instant):
        self._now = instant

    def reset(self):
        self._now = CLOCK_DEFAULT_UTC


clock = LogicalClock()


# --------------------------------------------------------------------------
# Identifiers and timestamps
# --------------------------------------------------------------------------
def new_id():
    """Server-minted UUID carrying no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    """`api_request_id` - server generated, starts with `req_` (PRD 2.2)."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso(dt):
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    """Envelope timestamp - transport metadata, not a business instant."""
    return iso(datetime.now(timezone.utc))


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_iso8601(value):
    """Parse an ISO 8601 UTC instant. Returns None when the value is not a
    valid instant (the caller turns that into ERR_VALIDATION)."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        base = base - sign * delta
    return base


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; None when malformed."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def utc_date_string(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


# --------------------------------------------------------------------------
# Numbers (PRD 2.7) - round half up everywhere, never float arithmetic for
# money, cubic feet compared exactly with no tolerance.
# --------------------------------------------------------------------------
def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def ceil_units(total, per_unit):
    """ceil(total / per_unit) as an integer."""
    return int((dec(total) / dec(per_unit)).to_integral_value(rounding=ROUND_CEILING))


def days(n):
    return timedelta(days=n)


def hours(n):
    return timedelta(hours=n)


# --------------------------------------------------------------------------
# Domain enumerations and global constants (SCAFFOLD global_constants)
# --------------------------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "CaseManager",
    "IntakeCoordinator",
    "WarehouseLead",
    "DispatchPlanner",
    "Volunteer",
)

COUNTIES = ("NORTH", "CENTRAL", "SOUTH")
COUNTY_ORDER = ("NORTH", "CENTRAL", "SOUTH")
CATEGORIES = ("BED", "SOFA", "CRIB", "TABLE_SET", "DRESSER", "KITCHEN_KIT", "LINENS")
GRADES_ABCD = ("A", "B", "C", "D")
GRADES_ABC = ("A", "B", "C")

CATEGORY_PRIORITY = {
    "BED": 1, "CRIB": 2, "LINENS": 3, "TABLE_SET": 4,
    "DRESSER": 5, "SOFA": 6, "KITCHEN_KIT": 7,
}
CONDITION_RANK = {"A": 1, "B": 2, "C": 3}

REFERRAL_VALID_DAYS = 45
MAX_REVISIONS = 2
STRIKE_BAN_THRESHOLD = 2
BAN_DAYS = 90
BED_BUG_REMEDIATION_DAYS = 60
QUARANTINE_DAYS_STANDARD = 14
QUARANTINE_DAYS_LIVE_PEST = 21
TRUCK_LOCKOUT_HOURS = 72
MIN_FILL_RATIO_TO_SCHEDULE = Decimal("0.5")
VOLUNTEER_REST_BUFFER_MINUTES = 60
RUN_HOURS = Decimal("4.0")
RELIABILITY_NO_SHOW_PENALTY = Decimal("15.0")

WAREHOUSE_CAPACITY_CF = Decimal("400")
SOFT_RATIO_REJECT_THRESHOLD = Decimal("0.50")

# Warehouse occupancy counts units that are physically in the building.
OCCUPYING_STOCK_STATUSES = ("QUARANTINED", "AVAILABLE", "RESERVED", "STAGED")
