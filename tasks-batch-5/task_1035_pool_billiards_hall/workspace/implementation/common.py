"""Shared primitives: constants, errors, response envelope, datetime + money helpers."""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# --------------------------------------------------------------------------
# Domain constants (SCAFFOLD §global_constants + §1.3 calculation constants)
# --------------------------------------------------------------------------
CYCLE_DAYS = 30
NO_SHOW_GRACE_MINUTES = 15
NO_SHOW_SUSPEND_THRESHOLD = 3
CHECKIN_EARLY_MINUTES = 15
TURNOVER_BUFFER_MINUTES = 10
MIN_TOURNAMENT_ENTRIES = 4
DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)

PEAK_START_HOUR = 18
PEAK_END_HOUR = 24
PEAK_MULTIPLIER = Decimal("1.5")
MIN_BILLED_MINUTES = 30

HANDICAP_SPOT_CAP = 3
FNB_TAX_PCT = Decimal("0.0875")
EVENT_TABLE_HOUR_RATE_CENTS = 4000
EVENT_DEPOSIT_PCT = Decimal("0.25")

# Enums
TABLE_TYPES = {"POOL_7FT", "POOL_9FT", "SNOOKER", "BILLIARDS"}
TIERS = {"BRONZE", "SILVER", "GOLD"}
TIER_RANK = {"BRONZE": 0, "SILVER": 1, "GOLD": 2}
FORMATS = {"SINGLE_ELIM", "DOUBLE_ELIM", "ROUND_ROBIN", "LEAGUE"}
HANDICAP_MODES = {"FULL", "CAPPED", "NONE"}
PRODUCT_CATEGORIES = {"CUE", "CASE", "ACCESSORY", "TABLE", "PART"}
SERVICE_TYPES = {"CUE_RETIP", "CUE_REPAIR", "TABLE_RECOVER"}

ROLES = {"Member", "FrontDesk", "Manager", "ProShopStaff"}

# --------------------------------------------------------------------------
# Error catalogue (SCAFFOLD §1.6 / PRD §5)
# --------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_TABLE_NOT_ACTIVE": 409,
    "ERR_DEPENDENT_STATE": 409,
    "ERR_TABLE_TIME_CONFLICT": 409,
    "ERR_EVENT_CAPACITY_UNAVAILABLE": 409,
    "ERR_CAPACITY_EXCEEDED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_PRECONDITION_NOT_MET": 409,
    "ERR_INSUFFICIENT_FUNDS": 402,
    "ERR_VALIDATION": 422,
    "ERR_MEMBER_SUSPENDED": 409,
    "ERR_STOCK_NEGATIVE": 422,
    "ERR_DUPLICATE": 409,
    "ERR_PAGINATION": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP[error_id]
        self.message = message or error_id


# --------------------------------------------------------------------------
# ID / request helpers
# --------------------------------------------------------------------------
def gen_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# --------------------------------------------------------------------------
# Datetime helpers — ISO 8601 UTC, three fractional digits
# --------------------------------------------------------------------------
def format_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime; return aware UTC datetime or raise ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("not a datetime string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# --------------------------------------------------------------------------
# Money helper
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal (or int) to a whole integer, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Serialization — convert internal record dict into a JSON-safe object
# --------------------------------------------------------------------------
def serialize(record):
    out = {}
    for k, v in record.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = format_dt(v)
        else:
            out[k] = v
    return out
