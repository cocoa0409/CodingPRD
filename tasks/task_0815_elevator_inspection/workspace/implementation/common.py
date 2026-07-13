"""Request-parsing, pagination, and lookup helpers."""

from flask import request

import errors
from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)


def get_body():
    """Return the JSON body as a dict.

    A missing/empty body is treated as {}. A body that is present but is not a
    JSON object (or is not valid JSON) is a malformed request.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def require_present(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request(f"Missing required field: {f}")


def require_string(body, field):
    require_present(body, field)
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string.")
    return val


def require_int(body, field):
    require_present(body, field)
    val = body[field]
    # Guard against bool (a subclass of int) being accepted as an integer.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    return val


def require_enum(body, field, allowed):
    val = require_string(body, field)
    if val not in allowed:
        raise errors.invalid_request(f"Field {field} has an invalid value: {val}")
    return val


def optional_enum(body, field, allowed):
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(f"Field {field} has an invalid value.")
    return val


def parse_pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_pagination()
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.invalid_pagination()
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_pagination()
        if offset < 0:
            raise errors.invalid_pagination()
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (stable via _seq), then slice."""
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def lookup(collection, resource_id, error_id):
    entity = collection.get(resource_id)
    if entity is None:
        raise errors.not_found(error_id)
    return entity
