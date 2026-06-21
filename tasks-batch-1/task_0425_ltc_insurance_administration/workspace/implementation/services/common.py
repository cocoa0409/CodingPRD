"""Shared request-parsing, pagination, and validation primitives."""
from flask import request

import errors


def get_json_body():
    """Parse the JSON body, tolerating empty bodies."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def paginate(items):
    """Apply limit/offset query params (PRD §2.3). Out-of-bounds ->
    ERR_VALIDATION_CONFLICT."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_CONFLICT, "Invalid limit")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_VALIDATION_CONFLICT, "limit out of bounds")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION_CONFLICT, "Invalid offset")
        if offset < 0:
            raise errors.err(errors.ERR_VALIDATION_CONFLICT, "offset out of bounds")

    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: " + name)


def require_str(body, name):
    require_fields(body, [name])
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be a non-empty string: " + name)
    return v


def require_int(body, name, non_negative=True):
    require_fields(body, [name])
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be an integer: " + name)
    if non_negative and v < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be non-negative: " + name)
    return v


def require_enum(body, name, allowed):
    v = require_str(body, name)
    if v not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid enum value for " + name)
    return v


def optional_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be a boolean: " + name)
    return v
