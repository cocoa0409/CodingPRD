"""Shared request/pagination/validation helpers."""
from decimal import Decimal, ROUND_HALF_UP
from flask import request

from errors import err, ERR_INVALID_REQUEST


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent/empty."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)


def require_enum(value, allowed, field_name):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, "Invalid value for %s" % field_name)


def parse_pagination():
    """limit defaults 10, min 1, max 100; offset defaults 0 (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3) using the monotonic _seq as
    a stable tiebreaker, then window."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


def round_half_up_2(value):
    """Round to two decimals, round-half-up, returning a float with 2 dp."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)
