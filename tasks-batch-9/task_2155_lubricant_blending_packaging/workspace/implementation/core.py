"""Foundation: logical clock, errors, response envelope, auth, validation helpers."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext, localcontext

from flask import g, request

getcontext().prec = 60

# --------------------------------------------------------------------------
# Error catalog (id -> http status)
# --------------------------------------------------------------------------
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_CUSTOMER_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CUSTOMER_NOT_FOUND": 404,
    "ERR_COMPONENT_LOT_NOT_FOUND": 404,
    "ERR_PRODUCT_SPEC_NOT_FOUND": 404,
    "ERR_BLEND_RECIPE_NOT_FOUND": 404,
    "ERR_BLEND_TANK_NOT_FOUND": 404,
    "ERR_BLEND_BATCH_NOT_FOUND": 404,
    "ERR_RETAIN_SAMPLE_NOT_FOUND": 404,
    "ERR_APPROVAL_CLAIM_NOT_FOUND": 404,
    "ERR_PACKAGE_CONFIGURATION_NOT_FOUND": 404,
    "ERR_PACKAGING_LINE_NOT_FOUND": 404,
    "ERR_PACKAGING_RUN_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_TAKEBACK_COLLECTION_NOT_FOUND": 404,
    "ERR_SPEC_CHANGE_REQUEST_NOT_FOUND": 404,
    "ERR_STALE_SPEC_VERSION": 412,
    "ERR_STALE_CUSTOMER_VERSION": 412,
    "ERR_INVALID_STATE": 409,
    "ERR_TANK_NOT_AVAILABLE": 409,
    "ERR_RECIPE_NOT_ACTIVE": 409,
    "ERR_SPEC_NOT_ACTIVE": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_CONFIG_NOT_ACTIVE": 409,
    "ERR_LINE_NOT_AVAILABLE": 409,
    "ERR_FLUSH_REQUIRED": 422,
    "ERR_HEEL_CONTAMINATION_EXCEEDED": 422,
    "ERR_LOT_QUARANTINED": 422,
    "ERR_TREAT_RATE_BELOW_SPEC": 422,
    "ERR_PREDICTED_VISCOSITY_OUT_OF_SPEC": 422,
    "ERR_CLAIM_NOT_SUBSTANTIATED": 422,
    "ERR_INSUFFICIENT_RETAINS": 422,
    "ERR_TANK_WINDOW_CONFLICT": 409,
    "ERR_LINE_CAPACITY_EXCEEDED": 409,
    "ERR_INVALID_WINDOW": 422,
    "ERR_RETENTION_WINDOW_ACTIVE": 422,
    "ERR_RECIPE_FRACTION_SUM": 422,
    "ERR_SPEC_REVISION_STALE": 409,
    "ERR_CLAIM_NOT_ACTIVE": 422,
    "ERR_NO_ELIGIBLE_RECIPE": 409,
    "ERR_TAKEBACK_AGREEMENT_INACTIVE": 409,
    "ERR_DUPLICATE_CLAIM": 409,
    "ERR_DUPLICATE_CODE": 409,
    "ERR_COMPONENT_SHORTAGE": 422,
    "ERR_CREDIT_LIMIT_EXCEEDED": 422,
    "ERR_NO_TAKEBACK_CREDIT": 422,
    "ERR_TANK_CAPACITY_EXCEEDED": 422,
    "ERR_VISCOSITY_REVIEW_BLOCKED": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = status if status is not None else ERRORS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, value):
        self.current = value
        return self.current


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sec(dt):
    """Whole-second resolution view of an instant."""
    if dt is None:
        return None
    return dt.replace(microsecond=0)


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, dp):
    """Round half up to `dp` decimal places, returning a Decimal."""
    q = Decimal(1).scaleb(-dp)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def log10(value):
    with localcontext() as ctx:
        ctx.prec = 50
        return D(value).log10()


def pow10(exponent):
    with localcontext() as ctx:
        ctx.prec = 50
        return Decimal(10) ** D(exponent)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    real = datetime.now(timezone.utc)
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(real),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }, status


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    return {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
        "response_type": "array",
        "data": items,
    }, 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
def to_json(record):
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = _convert(value)
    return out


def _convert(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, list):
        return [_convert(v) for v in value]
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items()}
    return value


def json_list(records):
    return [to_json(r) for r in records]


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
ROLES = [
    "PlatformAdmin",
    "ProductManager",
    "BlendOperator",
    "QCTechnician",
    "QualityManager",
    "ComplianceOfficer",
    "SalesRep",
    "Customer",
]


def authenticate(allowed_roles):
    """Rung 1 then rung 2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def is_customer_caller():
    return getattr(g, "role", None) == "Customer"


def caller_id():
    return getattr(g, "user_id", None)


# --------------------------------------------------------------------------
# Request-shape validation (rung 3)
# --------------------------------------------------------------------------
_MISSING = object()


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        if request.data.strip() == b"":
            return {}
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _get(b, name):
    return b.get(name, _MISSING)


def _missing(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def req_str(b, name):
    value = _get(b, name)
    if value is _MISSING or value is None:
        _missing(name)
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


def opt_str(b, name, default=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        _bad(name, "must be a string")
    return value


def req_enum(b, name, allowed):
    value = req_str(b, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(b, name, allowed, default=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def _as_number(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    return D(value)


def _range_check(name, value, gt=None, ge=None, lt=None, le=None):
    if gt is not None and not value > D(gt):
        _bad(name, "must be greater than %s" % gt)
    if ge is not None and not value >= D(ge):
        _bad(name, "must be at least %s" % ge)
    if lt is not None and not value < D(lt):
        _bad(name, "must be less than %s" % lt)
    if le is not None and not value <= D(le):
        _bad(name, "must be at most %s" % le)


def req_num(b, name, gt=None, ge=None, lt=None, le=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        _missing(name)
    number = _as_number(name, value)
    _range_check(name, number, gt, ge, lt, le)
    return number


def opt_num(b, name, default=None, gt=None, ge=None, lt=None, le=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        return default
    number = _as_number(name, value)
    _range_check(name, number, gt, ge, lt, le)
    return number


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    return value


def req_int(b, name, gt=None, ge=None, lt=None, le=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        _missing(name)
    number = _as_int(name, value)
    _range_check(name, D(number), gt, ge, lt, le)
    return number


def opt_int(b, name, default=None, gt=None, ge=None, lt=None, le=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        return default
    number = _as_int(name, value)
    _range_check(name, D(number), gt, ge, lt, le)
    return number


def req_bool(b, name):
    value = _get(b, name)
    if value is _MISSING or value is None:
        _missing(name)
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(b, name, default=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def req_dt(b, name):
    value = _get(b, name)
    if value is _MISSING or value is None:
        _missing(name)
    parsed = parse_dt(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC datetime")
    return parsed


def opt_dt(b, name, default=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        return default
    parsed = parse_dt(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 UTC datetime")
    return parsed


def req_str_list(b, name, default=None):
    value = _get(b, name)
    if value is _MISSING or value is None:
        return list(default) if default is not None else None
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        _bad(name, "must be an array of strings")
    return list(value)


# --------------------------------------------------------------------------
# Query-parameter validation (rung 3 for reads)
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def new_id():
    return str(uuid.uuid4())
