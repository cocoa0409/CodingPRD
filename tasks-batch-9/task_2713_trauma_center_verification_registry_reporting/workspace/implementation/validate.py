"""Band C helpers: payload shape (400) then enum membership (422), plus the
pagination bounds of PRD 2.3."""
from flask import request

from common import parse_dt
from errors import ApiError

_MISSING = object()


def get_body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return body


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key):
    value = body.get(key, _MISSING)
    if value is _MISSING or not isinstance(value, str) or value.strip() == "":
        bad()
    return value


def opt_str(body, key, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        bad()
    return value


def req_int(body, key, lo=None, hi=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or isinstance(value, bool) or not isinstance(value, int):
        bad()
    if lo is not None and value < lo:
        bad()
    if hi is not None and value > hi:
        bad()
    return value


def opt_int(body, key, lo=None, hi=None, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad()
    if lo is not None and value < lo:
        bad()
    if hi is not None and value > hi:
        bad()
    return value


def req_num(body, key, lo=None, hi=None, gt=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or isinstance(value, bool) or not isinstance(value, (int, float)):
        bad()
    if lo is not None and value < lo:
        bad()
    if hi is not None and value > hi:
        bad()
    if gt is not None and not value > gt:
        bad()
    return value


def req_dt(body, key):
    value = body.get(key, _MISSING)
    if value is _MISSING or not isinstance(value, str):
        bad()
    parsed = parse_dt(value)
    if parsed is None:
        bad()
    return parsed


def opt_dt(body, key, default=None):
    if not _present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        bad()
    parsed = parse_dt(value)
    if parsed is None:
        bad()
    return parsed


def check_enum(value, allowed):
    if value not in allowed:
        raise ApiError("ERR_INVALID_ENUM_VALUE")
    return value


def query_enum(name, allowed, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in allowed:
        raise ApiError("ERR_INVALID_ENUM_VALUE")
    return raw


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad()
        if limit < 1 or limit > 100:
            bad()
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad()
        if offset < 0:
            bad()
    return limit, offset


def paginate(records):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def filter_eq(records, field, param=None):
    value = request.args.get(param or field)
    if value is None or value == "":
        return records
    return [r for r in records if r.get(field) == value]
