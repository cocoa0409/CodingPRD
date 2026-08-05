"""Validation ladder helpers (PRD 2.6).

The ladder is strict: rungs are evaluated from 1 upward, the first rung whose
check fails decides the response, and no later rung runs.  Each route function
below calls these helpers in ascending rung order.
"""

from flask import request, g

import clock
import store
from constants import (
    ROLES,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MAX_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
)
from errors import ApiError
from timefmt import TimeFormatError, parse_instant, parse_date


# --------------------------------------------------------------------------
# Rungs 1 and 2 -- authentication and authorisation
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return role, user_id


# --------------------------------------------------------------------------
# Body access
# --------------------------------------------------------------------------
def body():
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


# --------------------------------------------------------------------------
# Rung 3 -- existence
# --------------------------------------------------------------------------
def path_row(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "No such %s: %s" % (collection, row_id))
    return row


def fk_row(payload, field, collection, required=True):
    """Resolve a body foreign key (rung 3).

    A field that is absent, null or not a string is left to rung 6; only a
    well-formed identifier that resolves to nothing is a rung-3 failure.
    """
    value = payload.get(field)
    if value is None or not isinstance(value, str):
        return None
    row = store.get(collection, value)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "No such %s: %s" % (collection, value))
    return row


# --------------------------------------------------------------------------
# Rung 6 -- required fields, declared JSON types, ranges and formats
# --------------------------------------------------------------------------
def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


def need(payload, field):
    if field not in payload or payload[field] is None:
        _fail("Field '%s' is required." % field)
    return payload[field]


def req_string(payload, field, min_len=None, max_len=None):
    value = need(payload, field)
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % field)
    if min_len is not None and len(value) < min_len:
        _fail("Field '%s' is shorter than %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        _fail("Field '%s' is longer than %d characters." % (field, max_len))
    return value


def opt_string(payload, field, min_len=None, max_len=None):
    if field not in payload or payload[field] is None:
        return None
    return req_string(payload, field, min_len, max_len)


def req_int(payload, field, minimum=None, maximum=None):
    value = need(payload, field)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %d." % (field, minimum))
    if maximum is not None and value > maximum:
        _fail("Field '%s' must be at most %d." % (field, maximum))
    return value


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_int(payload, field, minimum, maximum)


def req_bool(payload, field):
    value = need(payload, field)
    if not isinstance(value, bool):
        _fail("Field '%s' must be a boolean." % field)
    return value


def opt_bool(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_bool(payload, field)


def req_instant(payload, field):
    value = need(payload, field)
    try:
        return parse_instant(value)
    except TimeFormatError:
        _fail("Field '%s' must be an ISO 8601 UTC instant." % field)


def opt_instant(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_instant(payload, field)


def req_date(payload, field):
    value = need(payload, field)
    try:
        return parse_date(value)
    except TimeFormatError:
        _fail("Field '%s' must be a YYYY-MM-DD calendar date." % field)


def opt_date(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_date(payload, field)


def req_state_code(payload, field):
    value = req_string(payload, field)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        _fail("Field '%s' must be exactly two uppercase letters." % field)
    return value


def opt_state_code(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_state_code(payload, field)


def req_string_array(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return list(default) if default is not None else []
    value = payload[field]
    if not isinstance(value, list):
        _fail("Field '%s' must be an array." % field)
    for item in value:
        if not isinstance(item, str):
            _fail("Field '%s' must be an array of strings." % field)
    return list(value)


def enum_type_check(payload, field, required=False):
    """Rung 6 half of an enumerated field: presence and JSON type only."""
    if field not in payload or payload[field] is None:
        if required:
            _fail("Field '%s' is required." % field)
        return None
    if not isinstance(payload[field], str):
        _fail("Field '%s' must be a string." % field)
    return payload[field]


# --------------------------------------------------------------------------
# Rung 7 -- enum membership (closed routing list, 21 request fields)
# --------------------------------------------------------------------------
def check_enum(payload, field, allowed):
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_INVALID_ENUM",
            "Field '%s' must be one of: %s." % (field, ", ".join(allowed)),
        )
    return value


# --------------------------------------------------------------------------
# Rung 6 -- list pagination parameters
# --------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _fail("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            _fail("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _fail("Query parameter 'offset' must be an integer.")
        if offset < 0:
            _fail("Query parameter 'offset' must be at least 0.")
    return limit, offset


def apply_filters(rows, spec):
    """AND-combined filters; an unmatched but syntactically valid value yields an
    empty page rather than an error (PRD 2.3)."""
    result = rows
    for param, field in spec.items():
        value = request.args.get(param)
        if value is None or value == "":
            continue
        result = [r for r in result if r.get(field) == value]
    return result


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# --------------------------------------------------------------------------
# Row mutation bookkeeping (PRD 2.4 / 2.11)
# --------------------------------------------------------------------------
def touch(row):
    """Refresh updated_at and bump version by exactly one per request per row."""
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    row["updated_at"] = clock.now()
    if row["id"] in touched:
        return row
    touched.add(row["id"])
    row["version"] = row.get("version", 1) + 1
    return row


def mark_minted(row):
    """A row created by this request is not separately incremented by it."""
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    touched.add(row["id"])
    return row
