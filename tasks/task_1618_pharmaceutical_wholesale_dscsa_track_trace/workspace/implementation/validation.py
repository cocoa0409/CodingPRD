"""Request-body structural validation helpers (PRD §2.8).

Malformed bodies, missing required fields, and wrong-typed values surface
ERR_INVALID_REQUEST (400); unknown body-referenced FK ids surface
ERR_REFERENCE_NOT_FOUND (404); missing path ids surface ERR_NOT_FOUND (404).
"""
from flask import request

import db
import errors
from errors import ApiError


def get_body(required=True):
    """Return the JSON body as a dict. A missing/non-object body on an endpoint
    that declares inputs is malformed; otherwise treated as empty."""
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                           "Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                       "Request body must be a JSON object")
    return body


def _bad(field, why):
    raise ApiError(errors.ERR_INVALID_REQUEST[0], errors.ERR_INVALID_REQUEST[1],
                   "Field '%s' %s" % (field, why))


def req_str(body, field):
    v = body.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, str) or not v:
        _bad(field, "must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if v is None:
        _bad(field, "is required")
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    if minimum is not None and v < minimum:
        _bad(field, "must be >= %d" % minimum)
    return v


def opt_int(body, field, default=None, minimum=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    if minimum is not None and v < minimum:
        _bad(field, "must be >= %d" % minimum)
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return v


def req_datetime(body, field):
    v = body.get(field)
    if v is None:
        _bad(field, "is required")
    dt = db.parse_iso(v)
    if dt is None:
        _bad(field, "must be an ISO 8601 datetime string")
    return dt


def lookup(table, entity_id, pair, what):
    entity = table.get(entity_id) if isinstance(entity_id, str) else None
    if entity is None:
        raise ApiError(pair[0], pair[1], "%s '%s' does not exist" % (what, entity_id))
    return entity


def path_entity(table, entity_id, what):
    """Path-template identifier existence (priority 3 -> ERR_NOT_FOUND)."""
    return lookup(table, entity_id, errors.ERR_NOT_FOUND, what)


def body_fk(body, field, table, what):
    """Body-referenced FK existence (priority 4 -> ERR_REFERENCE_NOT_FOUND)."""
    v = body.get(field)
    if v is None:
        _bad(field, "is required")
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return lookup(table, v, errors.ERR_REFERENCE_NOT_FOUND, what)


def opt_body_fk(body, field, table, what):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return lookup(table, v, errors.ERR_REFERENCE_NOT_FOUND, what)
