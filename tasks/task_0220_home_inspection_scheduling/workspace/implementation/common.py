"""Shared helpers: common system fields, pagination, body parsing, validation
primitives, and request-body access.

Common fields (PRD §2.4):
  - Every resource carries `id` and `created_at`.
  - Most resources also carry `updated_at` and `version` (starts at 1, +1 per mutation).
  - Client and Agent are LEANER: only `id` and `created_at` (no updated_at, no version).
"""
from flask import request

import errors
from db import new_id, now_iso


def make_common(with_version=True):
    """Create the common system fields for a new entity."""
    ts = now_iso()
    base = {"id": new_id(), "created_at": ts}
    if with_version:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(entity):
    """Bump updated_at and version on a mutated entity that carries them."""
    if "version" in entity:
        entity["updated_at"] = now_iso()
        entity["version"] = entity["version"] + 1


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if absent / not a dict)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Out-of-bounds limit/offset or malformed date -> ERR_VALIDATION_RANGE (400).
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.validation_range("limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.validation_range("limit out of bounds.")

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.validation_range("offset must be an integer.")
        if offset < 0:
            raise errors.validation_range("offset out of bounds.")

    return limit, offset


def paginate(items, limit, offset):
    """Return (page_items, meta_pagination_dict). Items must already be sorted."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def sort_by_created(items):
    """Default list ordering: created_at ascending (stable on ties)."""
    return sorted(items, key=lambda e: e.get("created_at", ""))


# ---------------------------------------------------------------------------
# Field validation primitives (ERR_INVALID_REQUEST / 400).
# ---------------------------------------------------------------------------
def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request("Missing required field: %s" % name)
    return body[name]


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request("Field %s must be a non-empty string." % name)
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s below minimum." % name)
    if maximum is not None and val > maximum:
        raise errors.invalid_request("Field %s above maximum." % name)
    return val


def optional_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum=minimum, maximum=maximum)


def require_enum(body, name, members):
    val = require_field(body, name)
    if not isinstance(val, str) or val not in members:
        raise errors.invalid_request("Field %s must be one of %s." % (name, sorted(members)))
    return val


def require_number(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request("Field %s must be a number." % name)
    if minimum is not None and val < minimum:
        raise errors.invalid_request("Field %s below minimum." % name)
    if maximum is not None and val > maximum:
        raise errors.invalid_request("Field %s above maximum." % name)
    return val


def optional_number(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return require_number(body, name, minimum=minimum, maximum=maximum)
