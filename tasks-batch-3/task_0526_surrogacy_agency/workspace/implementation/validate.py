"""Request-body / query validation helpers."""
from flask import request

from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_VALIDATION_LIMIT,
    ERR_NOT_FOUND,
)


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict when absent)."""
    if request.content_length in (None, 0):
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    value = require_field(body, name)
    if not isinstance(value, str) or value == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return value


def require_int_cents(body, name):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if value < 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= 0" % name)
    return value


def require_int(body, name):
    value = require_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    return value


def require_enum(body, name, allowed):
    value = require_field(body, name)
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return value


def require_state_code(body, name):
    value = require_string(body, name)
    if len(value) != 2 or not value.isalpha() or value.upper() != value:
        raise err(ERR_INVALID_REQUEST, "Field %s must be a 2-letter uppercase state code" % name)
    return value


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_LIMIT, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION_LIMIT, "limit must be within [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION_LIMIT, "offset must be >= 0")
        if offset < 0:
            raise err(ERR_VALIDATION_LIMIT, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; returns page slice."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    return sorted(items, key=lambda o: (o["created_at"], o["_seq"]))


def lookup_or_404(collection, resource_id):
    obj = collection.get(resource_id)
    if obj is None:
        raise err(ERR_NOT_FOUND, "Resource not found: %s" % resource_id)
    return obj
