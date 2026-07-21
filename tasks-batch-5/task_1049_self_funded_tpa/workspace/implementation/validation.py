"""Body parsing, field validation, pagination parsing, money rounding."""
from decimal import Decimal, ROUND_HALF_UP
from flask import request

import errors
from errors import fail
from envelope import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MIN,
    PAGE_LIMIT_MAX,
    PAGE_OFFSET_DEFAULT,
)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail(errors.ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        fail(errors.ERR_VALIDATION, "Field '%s' must be a non-empty string" % field)
    return v


def optional_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        fail(errors.ERR_VALIDATION, "Field '%s' must be a string" % field)
    return v


def require_int_nonneg(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        fail(errors.ERR_VALIDATION, "Field '%s' must be an integer" % field)
    if v < 0:
        fail(errors.ERR_VALIDATION, "Field '%s' must be non-negative" % field)
    return v


def optional_int_nonneg(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int_nonneg(body, field)


def require_ratio(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail(errors.ERR_VALIDATION, "Field '%s' must be a number" % field)
    if v < 0 or v > 1:
        fail(errors.ERR_VALIDATION, "Field '%s' must be between 0 and 1" % field)
    return v


def optional_ratio(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    return require_ratio(body, field)


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        fail(errors.ERR_VALIDATION, "Field '%s' must be a boolean" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        fail(errors.ERR_VALIDATION, "Field '%s' must be one of %s" % (field, sorted(allowed)))
    return v


def require_date(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        fail(errors.ERR_VALIDATION, "Field '%s' must be an ISO date string" % field)
    _ensure_parseable(v, field)
    return v


def optional_date(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return require_date(body, field)


def _ensure_parseable(v, field):
    from store import parse_dt
    try:
        parse_dt(v)
    except (ValueError, TypeError):
        fail(errors.ERR_VALIDATION, "Field '%s' is not a valid ISO date/datetime" % field)


def require_billed_lines(body, field):
    v = body.get(field)
    if not isinstance(v, list) or len(v) == 0:
        fail(errors.ERR_VALIDATION, "Field '%s' must be a non-empty array" % field)
    out = []
    for line in v:
        if not isinstance(line, dict):
            fail(errors.ERR_VALIDATION, "Each billed line must be an object")
        bc = line.get("billed_cents")
        if isinstance(bc, bool) or not isinstance(bc, int) or bc < 0:
            fail(errors.ERR_VALIDATION, "Each billed line needs a non-negative integer billed_cents")
        item = {"billed_cents": bc}
        if "description" in line and line.get("description") is not None:
            if not isinstance(line["description"], str):
                fail(errors.ERR_VALIDATION, "billed line description must be a string")
            item["description"] = line["description"]
        else:
            item["description"] = None
        out.append(item)
    return out


def require_id_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or len(v) == 0:
        fail(errors.ERR_VALIDATION, "Field '%s' must be a non-empty array" % field)
    for item in v:
        if not isinstance(item, str) or item == "":
            fail(errors.ERR_VALIDATION, "Field '%s' must contain id strings" % field)
    return list(v)


def parse_pagination():
    args = request.args
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            fail(errors.ERR_VALIDATION, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN:
            limit = PAGE_LIMIT_MIN
        elif limit > PAGE_LIMIT_MAX:
            limit = PAGE_LIMIT_MAX
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            fail(errors.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def round_half_up_cents(int_amount, ratio):
    """round_half_up(int_amount * ratio) -> integer cents."""
    product = Decimal(int(int_amount)) * Decimal(str(ratio))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
