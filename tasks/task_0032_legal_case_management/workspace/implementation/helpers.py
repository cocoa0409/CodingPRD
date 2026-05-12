"""Common helpers: pagination, OCC, body parsing, money/rounding utilities."""

from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
import errors


PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


def parse_pagination():
    args = request.args
    limit = args.get("limit", PAGINATION_DEFAULTS["limit"])
    offset = args.get("offset", PAGINATION_DEFAULTS["offset"])

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "limit must be an integer.")
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "offset must be an integer.")

    if limit < PAGINATION_DEFAULTS["min"] or limit > PAGINATION_DEFAULTS["max"]:
        errors.raise_error(
            errors.ERR_VALIDATION_FAILED,
            f"limit must be between {PAGINATION_DEFAULTS['min']} and {PAGINATION_DEFAULTS['max']}.",
        )
    if offset < 0:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset : offset + limit], total


def get_json_body():
    """Return request JSON body as dict, or empty dict if missing."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "Request body must be a JSON object.")
    return body


def check_occ(entity, supplied_version):
    """Raise ERR_VERSION_MISMATCH if supplied_version is provided and mismatches."""
    if supplied_version is None:
        return
    try:
        v = int(supplied_version)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_VERSION_MISMATCH, "version must be an integer.")
    if v != entity.get("version"):
        errors.raise_error(errors.ERR_VERSION_MISMATCH, "version does not match server-side value.")


def bump(entity):
    """Refresh updated_at and bump version. Returns entity for chaining."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 0) + 1
    return entity


def common_create():
    """Return a dict with common create fields (created_at, updated_at, version=1)."""
    now = clock.now()
    return {"created_at": now, "updated_at": now, "version": 1}


def round_half_up(value):
    """Round a numeric value (Decimal/int/float) half-up to the nearest integer (cent)."""
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def require(body, field):
    if field not in body or body[field] is None:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Missing required field '{field}'.")
    return body[field]


def require_int(body, field, *, min_val=None, max_val=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Field '{field}' must be an integer.")
    if min_val is not None and val < min_val:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Field '{field}' must be >= {min_val}.")
    if max_val is not None and val > max_val:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Field '{field}' must be <= {max_val}.")
    return val


def require_str(body, field, *, min_len=None, max_len=None):
    val = require(body, field)
    if not isinstance(val, str):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Field '{field}' must be a string.")
    if min_len is not None and len(val) < min_len:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Field '{field}' must be at least {min_len} chars.")
    if max_len is not None and len(val) > max_len:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Field '{field}' must be at most {max_len} chars.")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        errors.raise_error(errors.ERR_VALIDATION_FAILED, f"Field '{field}' must be one of {sorted(allowed)}.")
    return val
