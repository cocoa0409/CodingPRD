"""Shared primitives: decimals, datetimes, dates, schema validation helpers."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from errors import ApiError

ROLES = (
    "benefits_admin",
    "network_admin",
    "care_coordinator",
    "provider_manager",
    "employee_user",
)

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# decimal helpers
# --------------------------------------------------------------------------- #

def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """round_half_up to `places` decimals."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dceil(value):
    """Exact ceiling to an integer Decimal."""
    return D(value).to_integral_value(rounding=ROUND_CEILING)


def dfloor(value):
    return D(value).to_integral_value(rounding=ROUND_FLOOR)


def jnum(value):
    """JSON rendering for a `number`-typed field."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    d = D(value)
    return float(d)


# --------------------------------------------------------------------------- #
# datetime / date helpers
# --------------------------------------------------------------------------- #

def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


def parse_dt_value(value, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(error_id)
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except Exception:
        raise ApiError(error_id)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0)


def parse_date_value(value, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(error_id)
    raw = value.strip()
    try:
        return date.fromisoformat(raw)
    except Exception:
        raise ApiError(error_id)


def utc_date(dt):
    return dt.astimezone(UTC).date()


# --------------------------------------------------------------------------- #
# schema validation helpers  (band 1 -> ERR_INVALID_REQUEST unless overridden)
# --------------------------------------------------------------------------- #

def bad(error_id="ERR_INVALID_REQUEST", message=None):
    raise ApiError(error_id, message)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def require_object(body):
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad()
    return body


def present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, max_len=None, allow_empty=False, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        bad(error_id)
    return opt_str(body, key, max_len, allow_empty, error_id)


def opt_str(body, key, max_len=None, allow_empty=False, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not isinstance(value, str):
        bad(error_id)
    if not allow_empty and value.strip() == "":
        bad(error_id)
    if max_len is not None and len(value) > max_len:
        bad(error_id)
    return value


def req_enum(body, key, allowed, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        bad(error_id)
    return opt_enum(body, key, allowed, error_id)


def opt_enum(body, key, allowed, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        bad(error_id)
    return value


def req_bool(body, key, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        bad(error_id)
    return opt_bool(body, key, error_id)


def opt_bool(body, key, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not isinstance(value, bool):
        bad(error_id)
    return value


def req_int_field(body, key, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        bad(error_id)
    return opt_int_field(body, key, error_id)


def opt_int_field(body, key, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not is_int(value):
        bad(error_id)
    return value


def req_num_field(body, key, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        bad(error_id)
    return opt_num_field(body, key, error_id)


def opt_num_field(body, key, error_id="ERR_INVALID_REQUEST"):
    if key not in body or body[key] is None:
        return None
    value = body[key]
    if not is_num(value):
        bad(error_id)
    return D(value)


def check_range(value, low=None, high=None, error_id="ERR_INVALID_REQUEST"):
    if value is None:
        return value
    v = D(value)
    if low is not None and v < D(low):
        bad(error_id)
    if high is not None and v > D(high):
        bad(error_id)
    return value


def decimals_of(value):
    d = D(value).normalize()
    exponent = d.as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)


def hours_between(start, end):
    seconds = D((end - start).total_seconds())
    return seconds / D(3600)
