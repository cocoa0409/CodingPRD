"""Shared helpers: decimals, datetimes, request-body field validation, constants."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from errors import ApiError

# ---- Plant-wide constants (PRD §3, SCAFFOLD §1.3) ----
SCALE_MIN = Decimal("0.25")
SCALE_MAX = Decimal("8.0")

WASTE_FACTOR = Decimal("1.06")          # 1 + WASTE_PCT(0.06)
METERS_PER_UNIT = {"RETAIL": Decimal("0.42"), "FOODSERVICE": Decimal("0.35")}
CASE_UNITS = {"RETAIL": 12, "FOODSERVICE": 6}

MIN_DWELL_HOURS = 4
HIGH_TEMP_FACTOR = Decimal("1.25")
CORE_TARGET_C = Decimal("-18")
VERIFY_GRACE_HOURS = 2

LOT_QUARANTINE_THRESHOLD = 3
# RECIPE_RATE_THRESHOLD 0.005 == 1/200: affected/shipped >= 1/200  <=>  200*affected >= shipped
RATE_NUM = 1
RATE_DEN = 200
WINDOW_DAYS = 90

DEEP_SHELF_LIFE_THRESHOLD_DAYS = 545
ALLERGEN_CHANGEOVER_MINUTES = 120
DEFAULT_CHANGEOVER_MINUTES = 45

PRODUCT_STYLES = {"ENTREE", "BOWL", "SKILLET"}
COMPONENT_TYPES = {"RAW_INGREDIENT", "SUB_ASSEMBLY", "PACKAGING"}
UNITS_OF_MEASURE = {"KG", "L", "EACH", "M"}
BILLING_METHODS = {"PER_CASE", "PER_KG"}
PACK_FORMATS = {"RETAIL", "FOODSERVICE"}
LINE_TYPES = {"TRAY", "POUCH"}
FILM_TYPES = {"TRAY_FILM", "POUCH_FILM"}
CHECK_TYPES = {"METAL_DETECTOR", "XRAY"}
ZONES = {"FREEZER_A", "FREEZER_B", "DEEP_FREEZE"}
TEMPERATURE_CLASSES = {"STANDARD", "DEEP"}
COMPLAINT_TYPES = {"FREEZER_BURN", "TEXTURE", "FOREIGN_MATERIAL", "OFF_ODOR"}
VERDICTS = {"VALID", "INVALID"}

# pack_format -> required line_type (PRD §3.5)
REQUIRED_LINE_TYPE = {"RETAIL": "TRAY", "FOODSERVICE": "POUCH"}

D0_001 = Decimal("0.001")
D0_01 = Decimal("0.01")
D1 = Decimal("1")


def dec(x):
    """JSON number -> Decimal via shortest repr (avoids binary float noise)."""
    return Decimal(str(x))


def q3(d):
    return d.quantize(D0_001, rounding=ROUND_HALF_UP)


def q2(d):
    return d.quantize(D0_01, rounding=ROUND_HALF_UP)


def q0(d):
    return d.quantize(D1, rounding=ROUND_HALF_UP)


def fnum(d):
    """Decimal -> JSON number."""
    if isinstance(d, Decimal):
        return float(d)
    return d


def is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def parse_dt(value, field):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO8601 datetime string" % field)
    t = value.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Aware datetime -> ISO 8601 UTC string with 'Z'."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def ceil_div(a, b):
    """Integer ceiling division for positive ints."""
    return -(-a // b)


def ceil_dec(d):
    return int(d.to_integral_value(rounding=ROUND_CEILING))


# ---- Request body field extraction / schema validation (pipeline stage 5) ----

def body_dict(json_body):
    if json_body is None:
        return {}
    if not isinstance(json_body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return json_body


def req_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def opt_present(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def as_string(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string" % field)
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of: %s" % (field, ", ".join(sorted(allowed))),
        )
    return value


def as_decimal(value, field):
    if not is_number(value):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number" % field)
    return dec(value)


def as_positive_decimal(value, field):
    d = as_decimal(value, field)
    if d <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be > 0" % field)
    return d


def as_int(value, field):
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % field)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer" % field)


def as_positive_int(value, field):
    i = as_int(value, field)
    if i <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be > 0" % field)
    return i


def as_nonnegative_int(value, field):
    i = as_int(value, field)
    if i < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be >= 0" % field)
    return i


def as_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % field)
    return value
