"""Shared primitives: errors, response envelope, logical clock, decimals, auth.

Every structural name (headers, envelope fields, pagination params, error ids)
is taken verbatim from SCAFFOLD.yaml / PRD.md for this task.
"""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
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
        self.message = message or error_id


def err(error_id, http_status, message=None):
    return ApiError(error_id, http_status, message)


def invalid_request(message):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


def invalid_enum(message):
    return ApiError("ERR_INVALID_ENUM_VALUE", 400, message)


def justification_too_short(message="justification must be at least 20 characters."):
    return ApiError("ERR_JUSTIFICATION_TOO_SHORT", 400, message)


def not_found(message="The requested resource does not exist."):
    return ApiError("ERR_NOT_FOUND", 404, message)


def conflict(error_id, message):
    return ApiError(error_id, 409, message)


# --------------------------------------------------------------------------
# Logical clock — default 2026-05-01T00:00:00Z; never falls back to wall time
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


CLOCK = Clock()


def logical_now():
    return CLOCK.now()


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


def rhu_int(value):
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# Parsing / body field validators (priority-4 request-shape checks)
# --------------------------------------------------------------------------


def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or not value.strip():
        raise invalid_request("%s must be an ISO-8601 datetime string." % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise invalid_request("%s must be an ISO-8601 datetime string." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, key):
    return parse_dt(req_present(body, key), key)


def opt_datetime(body, key, default=None):
    if not _present(body, key):
        return default
    return parse_dt(body[key], key)


_MISSING = object()


def _present(body, key):
    return isinstance(body, dict) and key in body and body[key] is not None


def req_present(body, key):
    if not _present(body, key):
        raise invalid_request("Field '%s' is required." % key)
    return body[key]


def req_string(body, key, min_len=1):
    value = req_present(body, key)
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be a string." % key)
    if len(value) < min_len:
        raise invalid_request("Field '%s' must be a non-empty string." % key)
    return value


def opt_string(body, key, min_len=1, default=None):
    if not _present(body, key):
        return default
    return req_string(body, key, min_len)


def req_justification(body, key):
    """A justification string: required, and >= 20 chars when present."""
    value = req_present(body, key)
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be a string." % key)
    if len(value) < 20:
        raise justification_too_short(
            "Field '%s' must be at least 20 characters." % key)
    return value


def opt_justification(body, key, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be a string." % key)
    if len(value) < 20:
        raise justification_too_short(
            "Field '%s' must be at least 20 characters." % key)
    return value


def _check_int(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request("Field '%s' must be an integer." % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    value = _check_int(req_present(body, key), key)
    if minimum is not None and value < minimum:
        raise invalid_request("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        raise invalid_request("Field '%s' is above its maximum." % key)
    return value


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        return default
    return req_int(body, key, minimum, maximum)


def req_enum(body, key, allowed):
    value = req_present(body, key)
    if not isinstance(value, str):
        raise invalid_request("Field '%s' must be a string." % key)
    if value not in allowed:
        raise invalid_enum(
            "Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, allowed)


def req_fk(body, key, table, label):
    """Body foreign-key reference must resolve to an existing row."""
    value = req_string(body, key)
    row = table.get(value)
    if row is None:
        raise invalid_request(
            "Field '%s' does not reference an existing %s." % (key, label))
    return row


def get_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


# --------------------------------------------------------------------------
# Auth — X-User-ID / X-User-Role headers; five declared roles
# --------------------------------------------------------------------------

ROLES = (
    "FacilityAdmin",
    "SpdTechnician",
    "SpdSupervisor",
    "OrScheduler",
    "QualityAuditor",
)

# "Any" admits every declared role (all read operations).
ANY = ROLES


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-Role header is required.")
    role = str(role)
    if role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "Unknown role '%s'." % role)
    return Actor(str(user_id), role)


def authorize(actor, allowed_roles):
    if actor.role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
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
# Pagination — limit (default 10, min 1, max 100), offset (default 0)
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
            raise invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(str(offset_raw))
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer.")
        if offset < 0:
            raise invalid_request("offset must be >= 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
