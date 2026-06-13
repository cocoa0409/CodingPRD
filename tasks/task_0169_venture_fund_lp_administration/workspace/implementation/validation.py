"""Request body / field validation helpers.

Validation precedence (PRD §2.8, SCAFFOLD §1.4):
  1 auth (ERR_UNAUTHENTICATED 401)
  2 role (ERR_FORBIDDEN_ROLE 403)
  3 ownership (ERR_NOT_COMMITMENT_OWNER 403)
  4 existence: path + FK left-to-right (ERR_RESOURCE_NOT_FOUND 404)
  5 required fields / types / enum members (ERR_INVALID_REQUEST 400)
  --- numeric range present-but-out-of-bounds -> ERR_VALIDATION_LIMIT 422
  6 state (ERR_INVALID_STATE 409)
  7 referential (ERR_INVALID_REFERENCE 422)
  ...
"""
from flask import request

import errors


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when none/empty.

    A malformed (non-JSON) body that is present yields ERR_INVALID_REQUEST.
    """
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            errors.fail(errors.ERR_INVALID_REQUEST, "Malformed JSON body.")
        if data is None:
            return {}
        if not isinstance(data, dict):
            errors.fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
        return data
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return body[field]


def require_string(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return val


def require_int(body, field):
    val = require(body, field)
    # bool is a subtype of int in Python; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return val


def require_enum(body, field, members):
    val = require(body, field)
    if not isinstance(val, str) or val not in members:
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be one of %s." % (field, members))
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean." % field)
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return val


def optional_array(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, list):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field %s must be an array." % field)
    return val


def check_range(value, field, lo=None, hi=None):
    """Present, well-typed, but out of declared range -> ERR_VALIDATION_LIMIT 422."""
    if lo is not None and value < lo:
        errors.fail(errors.ERR_VALIDATION_LIMIT, "Field %s below allowed minimum." % field)
    if hi is not None and value > hi:
        errors.fail(errors.ERR_VALIDATION_LIMIT, "Field %s above allowed maximum." % field)
    return value


# ---- Pagination (PRD §2.3) ----
# limit default 10, min 1, max 100; offset default 0, min 0.
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_PAGINATION_INVALID, "limit must be an integer.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            errors.fail(errors.ERR_PAGINATION_INVALID, "offset must be an integer.")
    if limit < 1 or limit > 100:
        errors.fail(errors.ERR_PAGINATION_INVALID, "limit out of range [1,100].")
    if offset < 0:
        errors.fail(errors.ERR_PAGINATION_INVALID, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Return (page, pagination_meta). items already sorted by created_at ASC."""
    total = len(items)
    window = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return window, meta


def sort_by_created(items):
    # Default list sort: created_at ASC (PRD §2.3). Stable tiebreak by id.
    return sorted(items, key=lambda o: (o["created_at"], o["id"]))
