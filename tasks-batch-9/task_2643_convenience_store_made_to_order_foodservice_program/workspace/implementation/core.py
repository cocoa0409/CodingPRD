"""In-memory store, logical clock, id/timestamp minting and arithmetic helpers.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded.  Every record is created through the declared API.
"""

import datetime
import random
import re
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from errors import ApiError

UTC = datetime.timezone.utc

# PRD 2.4 / SCAFFOLD global_conventions.logical_clock.default
CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

ROLES = (
    "ChainAdmin",
    "StoreManager",
    "KitchenAssociate",
    "ShiftLead",
    "FoodSafetyLead",
    "StoreTerminal",
    "Customer",
)

DAYPARTS = ("BREAKFAST", "LUNCH", "DINNER", "OVERNIGHT")
STATIONS = ("SANDWICH", "BEVERAGE", "HOT_FOOD", "BAKERY")
STATION_SEQUENCE = ("SANDWICH", "BEVERAGE", "HOT_FOOD", "BAKERY")

# ---------------------------------------------------------------------------
# constants pinned by the scaffold's calculation tables
# ---------------------------------------------------------------------------
PREMIUM_SURCHARGE_CENTS = 75
MODIFIER_PREP_SECONDS = 15
SANITATION_BUFFER_MINUTES = 15
CATERING_FEE_BP = 800
CATERING_MIN_FEE_CENTS = 500
CATERING_MIN_SUBTOTAL_CENTS = 5000
PREORDER_LEAD_MINUTES = 15
CATERING_LEAD_MINUTES = 720
MTO_TXNS_PER_LABOR_HOUR = 18
GRAB_TXNS_PER_LABOR_HOUR = 45
BAKERY_PREP_MINUTES = 120
PEAK_TXN_THRESHOLD = 400
PEAK_MULTIPLIER_BP = 11500
MIN_DAYPART_MINUTES = 180
PLUS_THRESHOLD = 500
ELITE_THRESHOLD = 2000
FUEL_COMBO_BONUS_POINTS = 50
FUEL_LOOKBACK_DAYS = 30
TEMP_LOG_WINDOW_MINUTES = 240
READY_COMPLIANCE_PCT = 90
NOT_READY_COMPLIANCE_PCT = 75
ABSOLUTE_MIN_READING_F = Decimal("-40")
ABSOLUTE_MAX_READING_F = Decimal("250")
TIER_MULTIPLIER_BP = {"BASIC": 10000, "PLUS": 12500, "ELITE": 15000}


class Database(object):
    """Plain dictionaries keyed by id.  Nothing is persisted to disk."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.stores = {}
        self.holding_units = {}
        self.menu_items = {}
        self.modifier_options = {}
        self.promotion_rules = {}
        self.loyalty_accounts = {}
        self.fuel_transactions = {}
        self.staffing_plans = {}
        self.production_batches = {}
        self.waste_logs = {}
        self.temperature_logs = {}
        self.corrective_actions = {}
        self.orders = {}
        self.order_lines = {}
        self.kitchen_tickets = {}
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Database()


def now():
    """The logical clock instant.  Nothing in this system reads wall time."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------------------
# datetime formatting / parsing
# ---------------------------------------------------------------------------
def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.6)."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_dt(dt):
    """ISO 8601 UTC; fractional digits only when the instant carries them."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        )
    return fmt_ms(dt)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_iso(value):
    """Parse an ISO 8601 UTC datetime; raise ERR_INVALID_REQUEST when malformed."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Expected an ISO 8601 UTC datetime string.")
    m = _DT_RE.match(value.strip())
    if not m:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO 8601 UTC datetime: %r" % value)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime.datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed ISO 8601 UTC datetime: %r" % value)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = datetime.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date (UTC)."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise ApiError("ERR_INVALID_REQUEST", "Expected a YYYY-MM-DD calendar date.")
    y, mo, d = (int(x) for x in value.strip().split("-"))
    try:
        datetime.date(y, mo, d)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Expected a YYYY-MM-DD calendar date.")
    return "%04d-%02d-%02d" % (y, mo, d)


def clock_date_str():
    c = db.clock
    return "%04d-%02d-%02d" % (c.year, c.month, c.day)


def plus_minutes(dt, minutes):
    return dt + datetime.timedelta(minutes=int(minutes))


def plus_seconds(dt, seconds):
    return dt + datetime.timedelta(seconds=int(seconds))


def daypart_for_instant(dt):
    """Daypart implied by the logical clock's UTC time-of-day, half-open."""
    h = dt.hour
    if 4 <= h < 11:
        return "BREAKFAST"
    if 11 <= h < 16:
        return "LUNCH"
    if 16 <= h < 22:
        return "DINNER"
    return "OVERNIGHT"


# ---------------------------------------------------------------------------
# arithmetic
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round half up on the absolute value, to a whole integer."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_div(numerator, denominator):
    """round_half_up(numerator / denominator) with exact decimal arithmetic."""
    return round_half_up(Decimal(numerator) / Decimal(denominator))


def ceil_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    return -((-numerator) // denominator)


def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Expected a numeric value.")


def gallons_q(value):
    """Gallons are recorded and summed at three decimal places."""
    return to_decimal(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def num_out(value):
    """Serialize a stored number as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


# ---------------------------------------------------------------------------
# record helpers
# ---------------------------------------------------------------------------
def base_record(versioned=True):
    rec = {"id": new_id(), "created_at": db.clock, "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = db.clock
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = db.clock
    rec["version"] = rec.get("version", 1) + 1


def sort_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
