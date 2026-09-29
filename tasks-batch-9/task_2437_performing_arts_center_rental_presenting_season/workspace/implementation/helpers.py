"""Auth, request-body validation, pagination and datetime helpers."""

import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

ROLES = (
    "CenterAdmin",
    "ProgrammingDirector",
    "RentalManager",
    "ArtistRepresentative",
    "RentalClientContact",
    "TechnicalDirector",
    "BoxOfficeManager",
    "FinanceController",
)


# --------------------------------------------------------------------------
# Auth (PRD section 2.1, validation steps 1-2)
# --------------------------------------------------------------------------
def actor():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    return user_id, role


def auth(*allowed_roles):
    user_id, role = actor()
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# --------------------------------------------------------------------------
# Body access
# --------------------------------------------------------------------------
def body():
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _invalid(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        _invalid(field, "is required")
    value = data[field]
    if not _is_int(value):
        _invalid(field, "must be an integer")
    if minimum is not None and value < minimum:
        _invalid(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _invalid(field, "must be <= %s" % maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum)


def req_num(data, field, minimum=None, maximum=None, max_decimals=None):
    if field not in data or data[field] is None:
        _invalid(field, "is required")
    value = data[field]
    if not _is_num(value):
        _invalid(field, "must be a number")
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        _invalid(field, "must be >= %s" % minimum)
    if maximum is not None and dec > Decimal(str(maximum)):
        _invalid(field, "must be <= %s" % maximum)
    if max_decimals is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_decimals:
            _invalid(field, "may carry at most %d decimal places" % max_decimals)
    return value


def opt_num(data, field, default=None, minimum=None, maximum=None, max_decimals=None):
    if field not in data or data[field] is None:
        return default
    return req_num(data, field, minimum, maximum, max_decimals)


def req_str(data, field):
    if field not in data or data[field] is None:
        _invalid(field, "is required")
    value = data[field]
    if not isinstance(value, str) or value.strip() == "":
        _invalid(field, "must be a non-empty string")
    return value


def req_bool(data, field):
    if field not in data or data[field] is None:
        _invalid(field, "is required")
    value = data[field]
    if not isinstance(value, bool):
        _invalid(field, "must be a boolean")
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_bool(data, field)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        _invalid(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def parse_dt(value, field):
    if not isinstance(value, str) or not value.strip():
        _invalid(field, "must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _invalid(field, "must be an ISO 8601 datetime string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(data, field):
    if field not in data or data[field] is None:
        _invalid(field, "is required")
    return data[field], parse_dt(data[field], field)


# --------------------------------------------------------------------------
# Pagination (PRD section 2.3)
# --------------------------------------------------------------------------
def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def page(items):
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }
    return window, meta


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def floor_days(later, earlier):
    """Whole days from `earlier` forward to `later`, truncated downward."""
    return int(math.floor((later - earlier).total_seconds() / 86400.0))
