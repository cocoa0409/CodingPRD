"""Auth header extraction, RBAC, and request-shape helpers.

Headers (PRD 2.1): X-User-ID identifies the acting principal, X-User-Role names
its role. Missing/empty either, or an unrecognised role, is ERR_UNAUTHENTICATED.
"""
from flask import request

import constants
import response
import util
from errors import fail

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate():
    """Step 1 of PRD 2.8. Returns (user_id, role)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in constants.ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role does not name a declared role.")
    return str(user_id).strip(), role


def require_roles(allowed):
    """Steps 1-2 of PRD 2.8. Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not use this endpoint." % role)
    return user_id, role


def body_json():
    """Parsed JSON object body; a non-object body is ERR_INVALID_REQUEST."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def pagination():
    """PRD 2.3 - limit/offset with declared bounds; out-of-bounds is 422."""
    limit = response.PAGINATION_DEFAULT_LIMIT
    offset = response.PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _as_int(raw_limit, "limit")
        if limit < response.PAGINATION_MIN_LIMIT or limit > response.PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _as_int(raw_offset, "offset")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def _as_int(raw, name):
    txt = str(raw).strip()
    try:
        return int(txt)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------- shape checks

def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def present(body, name):
    return name in body and body.get(name) is not None


def req_str(body, name, min_len=1, max_len=None):
    if not present(body, name):
        _bad(name, "is required.")
    value = body.get(name)
    if not isinstance(value, str):
        _bad(name, "must be a string.")
    if len(value) < min_len:
        _bad(name, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters." % max_len)
    return value


def opt_str(body, name, min_len=1, max_len=None, default=None):
    if not present(body, name):
        return default
    return req_str(body, name, min_len, max_len)


def req_enum(body, name, allowed):
    value = req_str(body, name, 1, None)
    if value not in allowed:
        _bad(name, "must be one of %s." % ", ".join(allowed))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_int(body, name, minimum=None, maximum=None):
    if not present(body, name):
        _bad(name, "is required.")
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %d." % maximum)
    return value


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if not present(body, name):
        return default
    return req_int(body, name, minimum, maximum)


def req_number(body, name, minimum=None):
    if not present(body, name):
        _bad(name, "is required.")
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number.")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s." % minimum)
    return value


def req_instant(body, name):
    value = req_str(body, name, 1, None)
    parsed = util.parse_date_only(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 timestamp.")
    return parsed


def opt_instant(body, name, default=None):
    if not present(body, name):
        return default
    return req_instant(body, name)


def req_jurisdiction(body, name):
    value = req_str(body, name, 2, 2)
    if not (value.isalpha() and value.isupper()):
        _bad(name, "must be exactly two uppercase letters.")
    return value


def req_list(body, name):
    if not present(body, name):
        _bad(name, "is required.")
    value = body.get(name)
    if not isinstance(value, list):
        _bad(name, "must be an array.")
    return value
