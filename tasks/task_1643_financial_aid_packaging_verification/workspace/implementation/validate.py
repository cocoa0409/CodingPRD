"""Request-body shape validation (rung 9) and path/body reference helpers
(rungs 3-4). All error ids come from the scaffold error catalog."""
from flask import request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
)
from util import is_valid_instant


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid non-empty string field: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not _is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} above maximum {maximum}")
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid boolean field: {field}")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_bool(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid enum field: {field}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, allowed)


def req_datetime(body, field):
    v = req_str(body, field)
    if not is_valid_instant(v):
        raise_error(ERR_INVALID_REQUEST, f"invalid ISO 8601 datetime: {field}")
    return v


def req_number(body, field):
    """A JSON number (int or float, not bool)."""
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"missing or invalid numeric field: {field}")
    return v


def require_path_resource(collection, rid):
    """Rung 3: path identifier existence (validated left-to-right by callers)."""
    obj = getattr(db, collection).get(rid)
    if obj is None:
        raise_error(ERR_NOT_FOUND, f"{collection} id not found: {rid}")
    return obj


def require_body_ref(collection, value, field):
    """Rung 4: a foreign key carried in the request body must resolve."""
    if not isinstance(value, str):
        # A non-string id cannot resolve; a null/missing FK defers to the rung-9
        # presence check via deferred_body_ref instead.
        raise_error(ERR_INVALID_REQUEST, f"invalid field type: {field}")
    obj = getattr(db, collection).get(value)
    if obj is None:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"{field} does not reference an existing entity: {value}")
    return obj


def deferred_body_ref(collection, body, field):
    """Rung 4 resolution that defers absent/null FKs to the rung-9 shape check.

    Returns None when the field is absent or null; the caller's rung-9
    req_str(body, field) then fails with ERR_INVALID_REQUEST. A present
    non-string value is a type error (400); a present unknown id is a
    reference error (404)."""
    v = body.get(field)
    if v is None:
        return None
    return require_body_ref(collection, v, field)


def get_pagination():
    """PRD 2.3: limit default 10 (min 1, max 100), offset default 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def opt_query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise_error(ERR_INVALID_REQUEST, f"query parameter {name} must be true or false")
