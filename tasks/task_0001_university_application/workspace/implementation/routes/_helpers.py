"""Helpers shared by route modules: request parsing, pagination, ownership."""

from flask import request

import errors


# --------------------------------------------------------------------------- #
# Request body
# --------------------------------------------------------------------------- #

def get_json_body() -> dict:
    """Return the request JSON body as a dict (empty dict if absent).

    A request with a body that fails to parse as JSON is rejected with
    ERR_INVALID_REQUEST. A request with no body returns an empty dict.
    """
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "Request body must be a JSON object.")
    return body


# --------------------------------------------------------------------------- #
# Type-checked field extraction
# --------------------------------------------------------------------------- #

_MISSING = object()


def require_field(body, name, *, kind, msg=None):
    if name not in body or body[name] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           msg or f"Field {name!r} is required.")
    return check_type(body[name], kind, name)


def optional_field(body, name, *, kind, default=None, allow_null=True):
    if name not in body:
        return default
    value = body[name]
    if value is None:
        if allow_null:
            return None
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           f"Field {name!r} cannot be null.")
    return check_type(value, kind, name)


def check_type(value, kind, name):
    if kind == "string":
        if not isinstance(value, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"Field {name!r} must be a string.")
        return value
    if kind == "integer":
        # Reject booleans — Python bool is a subclass of int, but a boolean is
        # not a legitimate integer here.
        if isinstance(value, bool) or not isinstance(value, int):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"Field {name!r} must be an integer.")
        return value
    if kind == "number":
        if isinstance(value, bool):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"Field {name!r} must be a number.")
        if not isinstance(value, (int, float)):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"Field {name!r} must be a number.")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               f"Field {name!r} must be a boolean.")
        return value
    return value


# --------------------------------------------------------------------------- #
# Pagination
# --------------------------------------------------------------------------- #

def parse_pagination():
    """Return (limit, offset) from query string, applying PRD §2.3 defaults.

    limit default 10, min 1, max 100.
    offset default 0, min 0.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Query parameter 'limit' must be in 1..100.")

    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Query parameter 'offset' must be an integer.")
        if offset < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "Query parameter 'offset' must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Slice the (already-sorted) list into a page; return (page, total)."""
    total = len(items)
    return items[offset:offset + limit], total
