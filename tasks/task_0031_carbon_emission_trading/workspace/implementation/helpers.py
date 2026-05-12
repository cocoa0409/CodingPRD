"""Common helpers: pagination, OCC, body parsing, decimal arithmetic."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

from flask import request

import clock
import errors


PAGINATION_DEFAULTS = {"limit": 10, "min": 1, "max": 100, "offset": 0}


# -------------------- Body / param parsing --------------------

def get_json_body():
    """Return request JSON body as dict, or empty dict if missing/non-dict."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_INPUT, "Request body must be a JSON object.")
    return body


def require_fields(body, fields):
    """Raise ERR_INVALID_INPUT if any required field is missing or None."""
    for f in fields:
        if f not in body or body[f] is None:
            errors.raise_error(errors.ERR_INVALID_INPUT, f"Missing required field: {f}")


def parse_pagination():
    args = request.args
    limit = args.get("limit", PAGINATION_DEFAULTS["limit"])
    offset = args.get("offset", PAGINATION_DEFAULTS["offset"])

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_INVALID_INPUT, "limit must be an integer.")
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_INVALID_INPUT, "offset must be an integer.")

    if limit < PAGINATION_DEFAULTS["min"] or limit > PAGINATION_DEFAULTS["max"]:
        errors.raise_error(
            errors.ERR_INVALID_INPUT,
            f"limit must be between {PAGINATION_DEFAULTS['min']} and {PAGINATION_DEFAULTS['max']}.",
        )
    if offset < 0:
        errors.raise_error(errors.ERR_INVALID_INPUT, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset : offset + limit], total


# -------------------- OCC / common-fields --------------------

def check_occ(entity, supplied_version):
    """Raise ERR_STALE_VERSION if supplied_version provided and mismatches."""
    if supplied_version is None:
        return
    try:
        v = int(supplied_version)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_STALE_VERSION, "version must be an integer.")
    if v != entity.get("version"):
        errors.raise_error(errors.ERR_STALE_VERSION, "version does not match server-side value.")


def bump(entity):
    """Refresh updated_at and bump version. Returns entity for chaining."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 0) + 1
    return entity


def common_create():
    """Return a dict with common create fields (created_at, updated_at, version=1)."""
    now = clock.now()
    return {"created_at": now, "updated_at": now, "version": 1}


# -------------------- Decimal arithmetic --------------------

TWO_PLACES = Decimal("0.01")


def to_dec(x):
    """Convert int/float/str/Decimal to Decimal. None -> Decimal(0)."""
    if x is None:
        return Decimal(0)
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


def round_half_up_2(x):
    """Round-half-up to 2 decimal places, return Decimal."""
    return to_dec(x).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_down_2(x):
    """Round-down (floor toward zero) to 2 decimal places, return Decimal."""
    return to_dec(x).quantize(TWO_PLACES, rounding=ROUND_DOWN)


def dec_to_float(d):
    """Render Decimal for JSON output as float."""
    if d is None:
        return None
    return float(d)


def fnum(x):
    """For computed numeric output: ensure Decimal -> float at serialization time."""
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    return x
