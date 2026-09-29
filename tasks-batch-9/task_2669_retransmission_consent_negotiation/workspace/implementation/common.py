"""Auth (PRD 2.1), request-shape validation (PRD 2.8 step 3) and pagination."""
from flask import request

from errors import ApiError
from store import ROLES, parse_iso


# --- step 1 and 2: headers, then role authorisation ------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# --- step 3: request shape -------------------------------------------------
def body_json(required=True):
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "A JSON request body is required.")
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if parsed is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "A JSON request body is required.")
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def present(body, field):
    return field in body and body[field] is not None


def take_int(body, field, minimum=None, maximum=None, required=True, default=None):
    if not present(body, field):
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %d" % maximum)
    return value


def take_str(body, field, min_len=1, max_len=None, required=True, default=None):
    if not present(body, field):
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    return value


def take_enum(body, field, allowed, required=True, default=None):
    if not present(body, field):
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def take_bool(body, field, required=False, default=False):
    if not present(body, field):
        if required:
            _bad(field, "is required")
        return default
    value = body[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def take_dt(body, field, required=True, default=None):
    if not present(body, field):
        if required:
            _bad(field, "is required")
        return default
    parsed = parse_iso(body[field])
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant")
    return parsed


def take_enum_list(body, field, allowed, required=True, min_items=1):
    if not present(body, field):
        if required:
            _bad(field, "is required")
        return None
    value = body[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if min_items is not None and len(value) < min_items:
        _bad(field, "must contain at least %d entry" % min_items)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad(field, "entries must each be one of %s" % ", ".join(allowed))
        if item not in seen:
            seen.append(item)
    return seen


# --- step 3: pagination ----------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not _is_int(raw_limit):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'limit' must be an integer.")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        if not _is_int(raw_offset):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'offset' must be an integer.")
        offset = int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'offset' must not be negative.")
    return limit, offset


def _is_int(text):
    text = str(text).strip()
    if text.startswith("-"):
        return text[1:].isdigit() and text[1:] != ""
    return text.isdigit()


def query_enum(field, allowed):
    value = request.args.get(field)
    if value is None:
        return None
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is invalid." % field)
    return value


def query_str(field):
    value = request.args.get(field)
    if value is None:
        return None
    return value


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return [serializer(row) for row in window], total
