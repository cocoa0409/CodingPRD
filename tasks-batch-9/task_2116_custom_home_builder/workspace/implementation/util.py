"""Response envelope, header auth, and request-body validation helpers."""
import json
import random
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import jsonify, request

from errors import AppError
from store import db, now

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "ProjectManager",
    "Estimator",
    "Controller",
    "Client",
    "Lender",
    "Subcontractor",
)

STAFF_FUNCTION_BY_ROLE = {
    "ProjectManager": "PROJECT_MANAGER",
    "Estimator": "ESTIMATOR",
    "Controller": "CONTROLLER",
}

ALL_ROLES = list(ROLES)

# --------------------------------------------------------------------------
# Timestamps (PRD 2.4)
# --------------------------------------------------------------------------


def parse_iso(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_iso(value):
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def add_days(instant, days):
    if instant is None:
        return None
    return instant + timedelta(days=int(days))


def whole_days(delta):
    """Whole days between two instants, truncated toward zero (PRD 2.5)."""
    return int(delta.total_seconds() / 86400.0)


# --------------------------------------------------------------------------
# Money (PRD 2.5)
# --------------------------------------------------------------------------
CENTS = Decimal("0.01")


def q2(value):
    """round_half_up to 2 decimal places."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def dsum(values):
    total = Decimal("0")
    for v in values:
        if v is not None:
            total += v
    return total


# --------------------------------------------------------------------------
# Envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_iso(now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime):
        return fmt_iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": _jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def ok_list(rows, page_meta, status=200):
    body = {
        "meta": _meta(page_meta),
        "response_type": "array",
        "data": [_jsonable(r) for r in rows],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# --------------------------------------------------------------------------
# Auth ladder steps 1-3 (PRD 2.10)
# --------------------------------------------------------------------------


def authorize(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise AppError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        raise AppError("ERR_UNAUTHENTICATED")
    role = role.strip()
    user_id = user_id.strip()
    if role not in ROLES:
        raise AppError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise AppError("ERR_FORBIDDEN_ROLE")
    return user_id, role


def check_staff_identity(user_id, role):
    """Ladder step 7 (PRD 2.10)."""
    expected = STAFF_FUNCTION_BY_ROLE.get(role)
    if expected is None:
        return None
    staff = db.staff_members.get(user_id)
    if staff is None or staff.get("staff_function") != expected:
        raise AppError("ERR_ROLE_IDENTITY_MISMATCH")
    return staff


# --------------------------------------------------------------------------
# Body parsing / field validation (ladder step 5)
# --------------------------------------------------------------------------


def parse_body():
    raw = request.get_data(as_text=True)
    if raw is None or not raw.strip():
        return {}
    try:
        body = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise AppError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise AppError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def _bad(field, reason):
    raise AppError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, reason))


def has(body, name):
    return name in body and body[name] is not None


def req_str(body, name):
    if name not in body or body[name] is None:
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        _bad(name, "must be a non-empty string")
    return value


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    return value


def req_id(body, name):
    return req_str(body, name)


def opt_id(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        _bad(name, "must be a non-empty string")
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, allowed)


def _as_decimal(name, value, max_dp=2):
    if isinstance(value, bool):
        _bad(name, "must be a number")
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(str(value))
    else:
        _bad(name, "must be a number")
    try:
        exponent = dec.as_tuple().exponent
    except (InvalidOperation, AttributeError):
        _bad(name, "must be a number")
    if not isinstance(exponent, int) or exponent < -max_dp:
        _bad(name, "must carry at most %d decimal places" % max_dp)
    return dec


def req_money(body, name, minimum=Decimal("0"), exclusive_min=False, maximum=None, max_dp=2):
    if name not in body or body[name] is None:
        _bad(name, "is required")
    dec = _as_decimal(name, body[name], max_dp=max_dp)
    if minimum is not None:
        if exclusive_min:
            if dec <= minimum:
                _bad(name, "must be strictly greater than %s" % minimum)
        elif dec < minimum:
            _bad(name, "must be at least %s" % minimum)
    if maximum is not None and dec > maximum:
        _bad(name, "must be at most %s" % maximum)
    return dec


def opt_money(body, name, default=None, minimum=Decimal("0"), exclusive_min=False,
              maximum=None, max_dp=2):
    if name not in body or body[name] is None:
        return default
    return req_money(body, name, minimum=minimum, exclusive_min=exclusive_min,
                     maximum=maximum, max_dp=max_dp)


def _as_int(name, value):
    if isinstance(value, bool):
        _bad(name, "must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        _bad(name, "must be an integer")
    if isinstance(value, float):
        if float(value).is_integer():
            return int(value)
        _bad(name, "must be an integer")
    _bad(name, "must be an integer")


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        _bad(name, "is required")
    value = _as_int(name, body[name])
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d" % maximum)
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name):
    if name not in body or body[name] is None:
        _bad(name, "is required")
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_bool(body, name)


def req_dt(body, name):
    if name not in body or body[name] is None:
        _bad(name, "is required")
    parsed = parse_iso(body[name])
    if parsed is None:
        _bad(name, "must be an ISO 8601 timestamp")
    return parsed


def opt_dt(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_dt(body, name)


# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise AppError("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            raise AppError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise AppError("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        if offset < 0:
            raise AppError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def qfilter(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
