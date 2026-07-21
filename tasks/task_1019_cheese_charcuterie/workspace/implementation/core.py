"""Core infrastructure: in-memory store, response envelope, errors, helpers."""
import math
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# Error catalog (id -> http status)
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_PRICING_CONFIG": 422,
    "ERR_INVALID_STATE": 409,
    "ERR_ORDER_NOT_DRAFT": 409,
    "ERR_ALREADY_PAID": 409,
    "ERR_ORDER_NOT_PAID": 409,
    "ERR_ORDER_NOT_FULFILLED": 409,
    "ERR_SUBSCRIPTION_INVALID_STATE": 409,
    "ERR_LOT_NOT_READY": 409,
    "ERR_STALE_LOT_VERSION": 412,
    "ERR_INSUFFICIENT_LOT_WEIGHT": 409,
    "ERR_CAVE_CAPACITY_EXCEEDED": 409,
    "ERR_RAW_MILK_AGING": 422,
    "ERR_EMPTY_ORDER": 422,
    "ERR_WHOLESALE_MIN_ORDER": 422,
    "ERR_INSUFFICIENT_STORE_CREDIT": 402,
    "ERR_PREP_STATION_CONFLICT": 409,
    "ERR_TASTING_ROOM_CONFLICT": 409,
    "ERR_TASTING_SEATS_EXCEEDED": 409,
    "ERR_CUSTOMER_NOT_ACTIVE": 409,
}


def err(error_id, message=None):
    return ApiError(error_id, ERRORS[error_id], message)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WHOLESALE_TIER_1_WEIGHT_G = 5000
WHOLESALE_TIER_2_WEIGHT_G = 20000
WHOLESALE_TIER_1_PCT = Decimal("0.08")
WHOLESALE_TIER_2_PCT = Decimal("0.15")
MAX_WHOLESALE_DISCOUNT_CENTS = 50000
DELIVERY_FEE_CENTS = 2500
BOARD_ASSEMBLY_FEE_CENTS = 1500
LOT_MAX_SHRINK_PCT = Decimal("0.35")
RAW_MILK_MIN_LEGAL_AGING_DAYS = 60
WHOLESALE_MIN_ORDER_CENTS = 10000

ROLES = {"ShopManager", "CounterStaff", "WholesaleCustomer"}
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Number / time helpers
# ---------------------------------------------------------------------------


def rhu(value):
    """Round half up to nearest integer."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(x):
    """Decimal from an int/float/str without binary float noise."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def parse_dt(s):
    if s is None:
        return None
    if not isinstance(s, str):
        raise err("ERR_VALIDATION", "invalid datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise err("ERR_VALIDATION", "invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_out(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (dt.microsecond // 1000))


def now_wall():
    return datetime.now(timezone.utc)


def now_iso():
    return iso_out(now_wall())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.customers = {}
        self.products = {}
        self.caves = {}
        self.lots = {}
        self.orders = {}
        self.order_lines = {}
        self.boards = {}
        self.subscriptions = {}
        self.prep_stations = {}
        self.tasting_rooms = {}
        self.tasting_events = {}
        self._seq = 0
        self.clock = parse_dt(DEFAULT_CLOCK)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_common(self):
        ts = now_iso()
        return {
            "id": str(uuid.uuid4()),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": self.next_seq(),
        }


DB = Store()


def touch(entity):
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()


def aging_days(lot):
    start = lot["_aging_start_dt"]
    delta = (DB.clock - start).total_seconds()
    days = math.floor(delta / 86400.0)
    return max(0, int(days))
