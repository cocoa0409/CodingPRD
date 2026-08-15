from flask import request

import errors as E
import response
from db import all_sorted, serialize
from errors import ApiError


def body():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def get_or_404(table, rid, label="resource"):
    rec = table.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise ApiError(E.ERR_NOT_FOUND, 404, f"{label} not found: {rid}")
    return rec


def _parse_int_param(raw, name, minimum, maximum=None):
    try:
        value = int(str(raw), 10)
    except (TypeError, ValueError):
        raise ApiError(E.ERR_VALIDATION, 400, f"{name} must be an integer")
    if value < minimum:
        raise ApiError(E.ERR_VALIDATION, 400, f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ApiError(E.ERR_VALIDATION, 400, f"{name} must be at most {maximum}")
    return value


def list_response(table, filters):
    """filters: list of (record_field, query_value) applied as equality when value present."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10 if raw_limit is None else _parse_int_param(raw_limit, "limit", 1, 100)
    offset = 0 if raw_offset is None else _parse_int_param(raw_offset, "offset", 0, None)
    items = all_sorted(table)
    for field, value in filters:
        if value is not None:
            items = [i for i in items if i.get(field) == value]
    total = len(items)
    page = items[offset : offset + limit]
    return response.arr([serialize(i) for i in page], limit, offset, total)


def is_intlike(v):
    return isinstance(v, int) and not isinstance(v, bool)


def opt_int(v):
    """int for integral ints/floats, else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None
