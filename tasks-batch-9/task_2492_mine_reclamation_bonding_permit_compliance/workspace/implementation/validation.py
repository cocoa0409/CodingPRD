"""Validation-ladder helpers: bands 1-5 (auth, role, schema, existence).

PRD 2.5 fixes the order in which a request is rejected. Handlers call these
helpers in the documented order and the first failure short-circuits.
"""

from datetime import datetime, timezone

from flask import request

from constants import (
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    LIMIT_DEFAULT,
    LIMIT_MAX,
    LIMIT_MIN,
    OFFSET_DEFAULT,
    OFFSET_MIN,
)
from db import D
from errors import ApiError


# ==========================================================================
# Band 1 + 2 — headers and role authorisation
# ==========================================================================
def authorize(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            "ERR_MISSING_AUTH_HEADERS",
            "Both X-User-ID and X-User-Role headers are required and must be non-empty.",
        )
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorised for this endpoint." % role,
        )
    return user_id, role


# ==========================================================================
# Band 3 — schema and constraint validity
# ==========================================================================
def get_body():
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def str_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


def enum_field(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def bool_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def number_field(body, name, required=True, default=None, gt=None, ge=None, le=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not _is_number(value):
        _bad(name, "must be a number")
    dec = D(value)
    if gt is not None and not dec > D(gt):
        _bad(name, "must be strictly greater than %s" % gt)
    if ge is not None and not dec >= D(ge):
        _bad(name, "must be greater than or equal to %s" % ge)
    if le is not None and not dec <= D(le):
        _bad(name, "must be less than or equal to %s" % le)
    return dec


def int_field(body, name, required=True, default=None, ge=None, le=None, gt=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, int) or isinstance(value, bool):
        _bad(name, "must be an integer")
    if gt is not None and not value > gt:
        _bad(name, "must be strictly greater than %s" % gt)
    if ge is not None and not value >= ge:
        _bad(name, "must be greater than or equal to %s" % ge)
    if le is not None and not value <= le:
        _bad(name, "must be less than or equal to %s" % le)
    return value


def parse_iso(value, name):
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 timestamp string")
    text = value.strip()
    if text == "":
        _bad(name, "must be an ISO 8601 timestamp string")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad(name, "must be an ISO 8601 timestamp string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def datetime_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad(name, "is required")
        return default
    return parse_iso(body[name], name)


# ==========================================================================
# Query-string validation (band 3 as well)
# ==========================================================================
def query_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)),
        )
    return value


def query_string(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value.strip() == "":
        raise ApiError(
            "ERR_INVALID_REQUEST", "Query parameter '%s' must be non-empty." % name
        )
    return value


def _query_int(name, default, minimum, maximum):
    if name not in request.args:
        return default
    raw = request.args.get(name)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name
        )
    if minimum is not None and value < minimum:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be at least %s." % (name, minimum),
        )
    if maximum is not None and value > maximum:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be at most %s." % (name, maximum),
        )
    return value


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


# ==========================================================================
# Bands 4 and 5 — existence
# ==========================================================================
def lookup(collection, row_id, error_id):
    if not isinstance(row_id, str) or row_id not in collection:
        raise ApiError(error_id)
    return collection[row_id]


def resolve(collection, row_id, error_id):
    """Band 5 body-reference resolution. The string-shape check for the same
    field belongs to band 3 and is performed earlier by the handler."""
    if row_id is None:
        return None
    if row_id not in collection:
        raise ApiError(error_id)
    return collection[row_id]
