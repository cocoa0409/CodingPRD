"""Shared request-parsing and pagination helpers (PRD §2.3, §2.7)."""
from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Parse the JSON body; an absent body is treated as {}. A present but
    malformed body raises ERR_VALIDATION."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_VALIDATION, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_VALIDATION, "Body must be a JSON object")
    return body


def parse_pagination():
    """Read limit/offset query params with PRD defaults and bounds.
    limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")

    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT:
            limit = PAGINATION_MIN_LIMIT
        elif limit > PAGINATION_MAX_LIMIT:
            limit = PAGINATION_MAX_LIMIT

    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list."""
    return items[offset:offset + limit]


def sort_by_creation(entities):
    """Sort by created_at ascending, tie-broken by internal _seq (PRD §2.3)."""
    return sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))


def require_int(body, field, *, minimum=None, required=True, allow_none=False):
    """Extract an integer field, raising ERR_VALIDATION on type/range issues."""
    if field not in body or body[field] is None:
        if allow_none:
            return None
        if required:
            raise errors.err(errors.ERR_VALIDATION, "Missing required field: %s" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_VALIDATION, "%s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_VALIDATION, "%s must be >= %d" % (field, minimum))
    return val


def require_str(body, field, *, required=True, allow_none=False):
    """Extract a non-empty string field."""
    if field not in body or body[field] is None:
        if allow_none:
            return None
        if required:
            raise errors.err(errors.ERR_VALIDATION, "Missing required field: %s" % field)
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_VALIDATION, "%s must be a non-empty string" % field)
    return val


def require_enum(body, field, allowed, *, required=True):
    """Extract a string field constrained to an enum set."""
    val = require_str(body, field, required=required)
    if val is None:
        return None
    if val not in allowed:
        raise errors.err(errors.ERR_VALIDATION, "%s must be one of %s" % (field, sorted(allowed)))
    return val


def require_bool(body, field, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise errors.err(errors.ERR_VALIDATION, "Missing required field: %s" % field)
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_VALIDATION, "%s must be a boolean" % field)
    return val
