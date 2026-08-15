"""Request shape validation helpers (validation priority 3 -> ERR_INVALID_REQUEST)."""
from datetime import date
from decimal import Decimal

from flask import request

from db import db
from errors import raise_error, not_found, ERR_INVALID_REQUEST
from util import parse_date

_SENTINEL = object()


def get_body() -> dict:
    data = request.get_json(force=True, silent=True)
    return data if isinstance(data, dict) else {}


def req_str(body: dict, field: str) -> str:
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"{field} is required and must be a non-empty string")
    return v


def opt_str(body: dict, field: str, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return v


def req_enum(body: dict, field: str, allowed, default=_SENTINEL):
    v = body.get(field, _SENTINEL)
    if v is _SENTINEL or v is None:
        if default is _SENTINEL:
            raise_error(ERR_INVALID_REQUEST, f"{field} is required")
        return default
    if not isinstance(v, str) or v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return v


def req_int(body: dict, field: str, min_value=None) -> int:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be >= {min_value}")
    return v


def opt_int(body: dict, field: str, min_value=None, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be >= {min_value}")
    return v


def req_decimal(body: dict, field: str, gt: Decimal = None, gte: Decimal = None) -> Decimal:
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a number")
    d = Decimal(str(v))
    if gt is not None and not (d > gt):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be > {gt}")
    if gte is not None and not (d >= gte):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be >= {gte}")
    return d


def opt_decimal(body: dict, field: str, gt: Decimal = None, gte: Decimal = None):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a number")
    d = Decimal(str(v))
    if gt is not None and not (d > gt):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be > {gt}")
    if gte is not None and not (d >= gte):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be >= {gte}")
    return d


def req_date(body: dict, field: str) -> str:
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"{field} is required")
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an ISO date string")
    try:
        parse_date(v)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a valid ISO date (YYYY-MM-DD)")
    return v.strip()


def opt_date(body: dict, field: str):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an ISO date string")
    try:
        parse_date(v)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a valid ISO date (YYYY-MM-DD)")
    return v.strip()


def require_path_resource(collection: str, rid: str, what: str = "resource"):
    rec = db[collection].get(rid)
    if rec is None:
        not_found(what)
    return rec


def require_fk(collection: str, rid, what: str):
    if rid is None:
        raise_error(ERR_INVALID_REQUEST, f"{what} id is required")
    rec = db[collection].get(rid)
    if rec is None:
        not_found(what)
    return rec


def get_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
