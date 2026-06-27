"""Shared validation + pagination helpers (PRD §2.3, §2.11)."""
from flask import request

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MIN,
    PAGE_LIMIT_MAX,
    PAGE_OFFSET_DEFAULT,
)
from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict, or {} if absent. Malformed JSON or a
    non-object body raises ERR_VALIDATION."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Request body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def parse_pagination():
    """Return (limit, offset). Raises ERR_VALIDATION_PAGINATION if out of bounds."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise err(
                "ERR_VALIDATION_PAGINATION",
                "limit must be between %d and %d." % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX),
            )

    if offset_raw is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset must not be negative.")

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list. Returns (page_items, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def require_fields(body, names):
    """Ensure each name is present (and not None) in body. Raises ERR_VALIDATION."""
    for n in names:
        if body.get(n) is None:
            raise err("ERR_VALIDATION", "Missing required field: %s" % n)


def require_string(body, name):
    val = body.get(name)
    if not isinstance(val, str) or val == "":
        raise err("ERR_VALIDATION", "Field %s must be a non-empty string." % name)
    return val


def require_int(body, name, minimum=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", "Field %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION", "Field %s must be >= %d." % (name, minimum))
    return val


def optional_int(body, name, default, minimum=None):
    if name not in body or body.get(name) is None:
        return default
    return require_int(body, name, minimum=minimum)


def require_enum(body, name, allowed):
    val = body.get(name)
    if val not in allowed:
        raise err("ERR_VALIDATION", "Field %s must be one of %s." % (name, sorted(allowed)))
    return val


def optional_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if not isinstance(val, bool):
        raise err("ERR_VALIDATION", "Field %s must be a boolean." % name)
    return val
