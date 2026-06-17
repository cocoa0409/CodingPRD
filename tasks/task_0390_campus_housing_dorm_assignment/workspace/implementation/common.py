"""Shared request-handling helpers: body parsing, pagination, sorting."""

from flask import request

import errors


def get_body():
    """Return the JSON body as a dict; tolerate empty bodies.

    A malformed (non-JSON) body raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def parse_pagination():
    """Parse and validate limit/offset query params (PRD §2.3).

    Defaults: limit=10 (1..100), offset=0 (>=0). Out-of-range -> ERR_VALIDATION_PAGINATION.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.validation_pagination("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.validation_pagination("limit must be between 1 and 100.")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.validation_pagination("offset must be an integer.")
        if offset < 0:
            raise errors.validation_pagination("offset must be >= 0.")

    return limit, offset


def sort_by_created(items):
    """Sort records by created_at ascending, breaking ties by insertion seq."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(items, limit, offset):
    """Return the page slice and the total count."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def require_fields(body, fields):
    """Raise ERR_INVALID_REQUEST if any required field is missing/None."""
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request("Missing required field: %s" % f)


def require_enum(body, field, allowed):
    """Validate that body[field] is one of allowed."""
    val = body.get(field)
    if val not in allowed:
        raise errors.invalid_request("Invalid value for %s." % field)
    return val


def require_int(body, field, min_value=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("%s must be an integer." % field)
    if min_value is not None and val < min_value:
        raise errors.invalid_request("%s out of range." % field)
    return val


def optional_int(body, field, default=None, min_value=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, min_value=min_value)
