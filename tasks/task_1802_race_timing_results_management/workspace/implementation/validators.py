"""Shared request-validation helpers: body parsing, field validators,
existence resolution, pagination (PRD sections 2.3, 2.7, 2.10)."""
import json

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import ok_list
from util import parse_dt, parse_date


def get_body(required=()):
    raw = request.get_data()
    if not raw or not raw.strip():
        data = {}
    else:
        try:
            data = json.loads(raw)
        except Exception:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Malformed JSON body")
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    for f in required:
        if f not in data or data[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")
    return data


def v_str(data, f):
    v = data.get(f)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {f} must be a string")
    return v


def v_int(data, f):
    v = data.get(f)
    if isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {f} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {f} must be an integer")


def v_num(data, f):
    v = data.get(f)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {f} must be a number")
    return v


def v_dt(data, f):
    dt = parse_dt(data.get(f))
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {f} must be an ISO 8601 datetime")
    return dt


def v_date(data, f):
    d = parse_date(data.get(f))
    if d is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {f} must be a YYYY-MM-DD date")
    return d


def v_enum(data, f, allowed):
    v = data.get(f)
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"Field {f} must be one of {', '.join(allowed)}",
        )
    return v


def get_or_404(store, key):
    e = store.get(key)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Resource not found: {key}")
    return e


def page_args():
    limit = 10
    offset = 0
    raw = request.args.get("limit")
    if raw is not None:
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    raw = request.args.get("offset")
    if raw is not None:
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def sorted_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def list_page(items, serializer):
    limit, offset = page_args()
    items = sorted_items(items)
    total = len(items)
    page = [serializer(e) for e in items[offset : offset + limit]]
    return ok_list(page, total, limit, offset)
