"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""

import secrets

from flask import jsonify, request

from db import now_iso
from errors import ERR_INVALID_REQUEST, ApiError


def _meta(pag=None):
    meta = {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": now_iso(),
    }
    if pag is not None:
        meta.update(pag)
    return meta


def success(data, code=200, pag=None):
    """Single-resource (or object payload) success envelope."""
    body = {
        "meta": _meta(pag),
        "response_type": "array" if pag is not None else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    resp = jsonify(body)
    resp.status_code = status
    return resp


def _int_param(raw, name, default, lo, hi):
    if raw is None:
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if str(raw).strip() not in (str(val),):
        # reject things like '1.5' or 'abc' cleanly
        try:
            val = int(float(raw))
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} must be an integer")
    if val < lo or val > hi:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"{name} out of range [{lo}, {hi}]")
    return val


def list_response(items):
    """Paginate (limit/offset; defaults 10/0; limit in [1,100]) and wrap."""
    limit = _int_param(request.args.get("limit"), "limit", 10, 1, 100)
    offset = _int_param(request.args.get("offset"), "offset", 0, 0, 1 << 62)
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success(page, 200, pag)


def serialize(obj):
    """Strip internal bookkeeping keys (prefixed '_') from a stored record."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def serialize_many(items):
    return [serialize(o) for o in items]


def sorted_items(items):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(items, key=lambda o: (o.get("created_at", ""), o.get("_seq", 0)))


def apply_filters(items, filterable):
    """Restrict items by equality on supplied query params drawn from `filterable`."""
    out = list(items)
    for field in filterable:
        raw = request.args.get(field)
        if raw is None:
            continue
        out = [o for o in out if _matches(o.get(field), raw)]
    return out


def _matches(value, raw):
    if value is None:
        return raw in ("null", "")
    if isinstance(value, bool):
        return raw.lower() == str(value).lower()
    if isinstance(value, int):
        try:
            return int(raw) == value
        except (TypeError, ValueError):
            return False
    return str(value) == raw
