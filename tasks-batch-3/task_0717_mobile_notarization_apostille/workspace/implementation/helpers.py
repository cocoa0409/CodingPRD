"""Body validation, pagination, and field-extraction helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            errors.fail(errors.ERR_INVALID_REQUEST, "Body must be a JSON object")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            errors.fail(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def req_str(body, field):
    require_fields(body, [field])
    v = body[field]
    if not isinstance(v, str) or v == "":
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def req_int(body, field):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


def opt_int(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


def req_score(body, field):
    v = req_int(body, field)
    if v < 0 or v > 100:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be within 0..100")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return v


def req_number(body, field):
    require_fields(body, [field])
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return v


def opt_number(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in allowed:
        errors.fail(errors.ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def pagination():
    """Parse limit/offset query params. Returns (limit, offset)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.fail(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            errors.fail(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC then seq, paginate. Returns (page, total)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> 0.01, places=0 -> 1
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
