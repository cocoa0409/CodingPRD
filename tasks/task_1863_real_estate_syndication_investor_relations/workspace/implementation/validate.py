"""Request-body shape validation, pagination, filters, optional OCC fields."""
from flask import request

from errors import raise_error
from util import is_valid_iso_datetime


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v.strip() == "":
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid field: {field}")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_error("ERR_INVALID_REQUEST", f"invalid field type: {field}")
    return v


def _check_int(v, field, minimum=None, maximum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid integer field: {field}")
    if minimum is not None and v < minimum:
        raise_error("ERR_INVALID_REQUEST", f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error("ERR_INVALID_REQUEST", f"field {field} above maximum {maximum}")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None:
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid integer field: {field}")
    return _check_int(v, field, minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return _check_int(body.get(field), field, minimum, maximum)


def _check_number(v, field, minimum=None, maximum=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid numeric field: {field}")
    if minimum is not None and v < minimum:
        raise_error("ERR_INVALID_REQUEST", f"field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise_error("ERR_INVALID_REQUEST", f"field {field} above maximum {maximum}")
    return v


def req_number(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if v is None:
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid numeric field: {field}")
    return _check_number(v, field, minimum, maximum)


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return default
    return _check_number(body.get(field), field, minimum, maximum)


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise_error("ERR_INVALID_REQUEST", f"missing or invalid enum field: {field}")
    return v


def req_datetime(body, field):
    v = req_str(body, field)
    if not is_valid_iso_datetime(v):
        raise_error("ERR_INVALID_REQUEST", f"invalid ISO datetime: {field}")
    return v


def opt_version(body, field, current, error_id):
    """Optional optimistic-concurrency field (PRD 2.7)."""
    if field not in body or body.get(field) is None:
        return
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_INVALID_REQUEST", f"invalid integer field: {field}")
    if v != current:
        raise_error(error_id, f"{field} does not match current version {current}")


def req_version(body, field, current, error_id):
    """Required optimistic-concurrency field (PRD 2.7)."""
    if field not in body or body.get(field) is None:
        raise_error("ERR_INVALID_REQUEST", f"missing required field: {field}")
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_INVALID_REQUEST", f"invalid integer field: {field}")
    if v != current:
        raise_error(error_id, f"{field} does not match current version {current}")


def pagination():
    """limit/offset per PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "invalid limit")
        if limit < 1 or limit > 100:
            raise_error("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "invalid offset")
        if offset < 0:
            raise_error("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def apply_filters(items, mapping):
    """Exact-match query filters: mapping of query param name -> record field."""
    out = []
    for it in items:
        ok = True
        for param, field in mapping.items():
            v = request.args.get(param)
            if v is None:
                continue
            if it.get(field) is None or str(it.get(field)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out
