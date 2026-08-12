"""Shared helpers: decimals, datetimes, request-body field validation, constants."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError

# ---- Plant-wide constants (PRD §2.6) ----
GRADE_RANK = {"INDUSTRIAL": 1, "FOOD": 2, "MEDICAL": 3}
BLEND_CAP = {"INDUSTRIAL": Decimal("0.40"), "FOOD": Decimal("0.15"), "MEDICAL": Decimal("0.00")}
TRIM_ALLOWANCE_FACTOR = Decimal("1.18")  # 1 + TRIM_ALLOWANCE_PCT(0.18)
SETUP_FEE = Decimal("250.00")
REGRIND_VALUE_PCT = Decimal("0.60")
PROTO_SHOT_LIMIT = 500
BOOTH_TURNOVER_MINUTES = 30
BOOTH_TURNOVER = timedelta(minutes=BOOTH_TURNOVER_MINUTES)

RESIN_TYPES = {"PETG", "HIPS", "ABS", "PP", "PC"}
GRADES = {"INDUSTRIAL", "FOOD", "MEDICAL"}

D0_001 = Decimal("0.001")
D0_01 = Decimal("0.01")
D0_0001 = Decimal("0.0001")


def dec(x):
    """JSON number -> Decimal via shortest repr (avoids binary float noise)."""
    return Decimal(str(x))


def q3(d):
    return d.quantize(D0_001, rounding=ROUND_HALF_UP)


def q2(d):
    return d.quantize(D0_01, rounding=ROUND_HALF_UP)


def q4(d):
    return d.quantize(D0_0001, rounding=ROUND_HALF_UP)


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
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def timedelta_seconds(td):
    return Decimal(td.days * 86400 + td.seconds) + (Decimal(td.microseconds) / Decimal(1000000))


# ---- Request body field extraction / schema validation (priority 3) ----

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


def as_nonnegative_decimal(value, field):
    d = as_decimal(value, field)
    if d < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be >= 0" % field)
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
