"""Shared primitives: errors, response envelope, logical clock, decimals, auth."""
import random
import re
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


def validation(message="Request body failed validation."):
    return ApiError("ERR_VALIDATION", 422, message)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

CLOCK_DEFAULT_UTC = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock(object):
    def __init__(self):
        self.current = CLOCK_DEFAULT_UTC

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt.astimezone(timezone.utc)
        return self.current

    def today(self):
        return self.current.astimezone(timezone.utc).date()


CLOCK = Clock()


def logical_now():
    return CLOCK.now()


def logical_today():
    return CLOCK.today()


# --------------------------------------------------------------------------
# Rendering — ONE renderer for every server-emitted datetime
# --------------------------------------------------------------------------


def render_dt(dt):
    """ISO-8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def render_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Decimal helpers
# --------------------------------------------------------------------------


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places, returning a Decimal."""
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def q2(value):
    return rhu(value, 2)


def q1(value):
    return rhu(value, 1)


def rhu_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field="date"):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise validation("%s must be a YYYY-MM-DD calendar date." % field)
    try:
        y, m, d = value.split("-")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        raise validation("%s must be a valid calendar date." % field)


def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or not value.strip():
        raise validation("%s must be an ISO-8601 datetime string." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise validation("%s must be an ISO-8601 datetime string." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Body field validators (all raise ERR_VALIDATION / 422)
# --------------------------------------------------------------------------

_MISSING = object()


def _present(body, key):
    return isinstance(body, dict) and key in body and body[key] is not None


def req_present(body, key):
    if not _present(body, key):
        raise validation("Field '%s' is required." % key)
    return body[key]


def req_string(body, key, min_len=1, max_len=None, pattern=None):
    value = req_present(body, key)
    if not isinstance(value, str):
        raise validation("Field '%s' must be a string." % key)
    if len(value) < min_len:
        raise validation("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        raise validation("Field '%s' is too long." % key)
    if pattern is not None and not re.match(pattern, value):
        raise validation("Field '%s' has an invalid format." % key)
    return value


def opt_string(body, key, min_len=1, max_len=None, default=None, pattern=None):
    if not _present(body, key):
        return default
    return req_string(body, key, min_len, max_len, pattern)


def _check_int(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation("Field '%s' must be an integer." % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    value = _check_int(req_present(body, key), key)
    if minimum is not None and value < minimum:
        raise validation("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        raise validation("Field '%s' is above its maximum." % key)
    return value


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        return default
    return req_int(body, key, minimum, maximum)


def _check_num(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise validation("Field '%s' must be a number." % key)
    return D(value)


def req_decimal(body, key, minimum=None, maximum=None, exclusive_min=False):
    value = _check_num(req_present(body, key), key)
    if minimum is not None:
        if exclusive_min and value <= D(minimum):
            raise validation("Field '%s' must be greater than %s." % (key, minimum))
        if not exclusive_min and value < D(minimum):
            raise validation("Field '%s' is below its minimum." % key)
    if maximum is not None and value > D(maximum):
        raise validation("Field '%s' is above its maximum." % key)
    return value


def opt_decimal(body, key, minimum=None, maximum=None, exclusive_min=False, default=None):
    if not _present(body, key):
        return default
    return req_decimal(body, key, minimum, maximum, exclusive_min)


def req_bool(body, key):
    value = req_present(body, key)
    if not isinstance(value, bool):
        raise validation("Field '%s' must be a boolean." % key)
    return value


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    return req_bool(body, key)


def req_enum(body, key, allowed):
    value = req_present(body, key)
    if not isinstance(value, str) or value not in allowed:
        raise validation("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, allowed)


def get_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

ROLES = (
    "DistrictAdmin",
    "FieldTech",
    "LabAnalyst",
    "VectorEcologist",
    "AbatementManager",
    "SensitiveSiteOperator",
    "Resident",
)

ALL_DISTRICT_READERS = (
    "DistrictAdmin", "FieldTech", "LabAnalyst", "VectorEcologist", "AbatementManager",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", 401, "X-User-Role header is required.")
    role = str(role)
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Unknown role '%s'." % role)
    return Actor(str(user_id), role)


def authorize(actor, allowed_roles):
    if actor.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role %s may not call this endpoint." % actor.role)
    return actor


def auth(allowed_roles):
    return authorize(authenticate(), allowed_roles)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_dt(datetime.now(timezone.utc)),
    }


def jsonable(value):
    if isinstance(value, dict):
        return dict((k, jsonable(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return render_dt(value)
    if isinstance(value, date):
        return render_date(value)
    return value


def ok(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data) if data is not None else {},
    }
    return jsonify(payload), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": [jsonable(i) for i in items],
    }
    return jsonify(payload), 200


def error_response(error_id, http_status, message):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), http_status


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


def pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(str(limit_raw))
        except (TypeError, ValueError):
            raise validation("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise validation("limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(str(offset_raw))
        except (TypeError, ValueError):
            raise validation("offset must be an integer.")
        if offset < 0:
            raise validation("offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise validation("%s must be one of %s." % (name, sorted(allowed)))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise validation("%s must be a boolean." % name)


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# --------------------------------------------------------------------------
# Misc constants
# --------------------------------------------------------------------------

DAY = timedelta(days=1)
