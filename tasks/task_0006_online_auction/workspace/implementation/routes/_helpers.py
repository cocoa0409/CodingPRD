from flask import request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
)


def get_json_body() -> dict:
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length and request.content_length > 0:
            try:
                body = request.get_json(silent=False, force=True)
            except Exception:
                raise_err(ERR_INVALID_REQUEST, "Malformed JSON body")
            if body is None:
                return {}
            if not isinstance(body, dict):
                raise_err(ERR_INVALID_REQUEST, "Body must be a JSON object")
            return body
    return {}


def require_string(body: dict, key: str, min_len: int = 1, max_len: int = None, optional: bool = False, default=None):
    if key not in body:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    val = body[key]
    if val is None:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Field {key} cannot be null")
    if not isinstance(val, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be a string")
    if len(val) < min_len:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} too short")
    if max_len is not None and len(val) > max_len:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} too long")
    return val


def require_int(body: dict, key: str, min_val=None, max_val=None, optional: bool = False, default=None):
    if key not in body:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    val = body[key]
    if val is None:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Field {key} cannot be null")
    if isinstance(val, bool) or not isinstance(val, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be an integer")
    if min_val is not None and val < min_val:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} below minimum")
    if max_val is not None and val > max_val:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} above maximum")
    return val


def require_enum(body: dict, key: str, allowed, optional: bool = False, default=None):
    if key not in body:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    val = body[key]
    if val is None:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Field {key} cannot be null")
    if val not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be one of {sorted(allowed)}")
    return val


def require_datetime(body: dict, key: str, optional: bool = False, default=None):
    if key not in body:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {key}")
    val = body[key]
    if val is None:
        if optional:
            return default
        raise_err(ERR_INVALID_REQUEST, f"Field {key} cannot be null")
    try:
        return db.parse_dt(val)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, f"Field {key} must be ISO 8601 datetime")


def check_occ(entity: dict, body: dict):
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or body["version"] != entity.get("version"):
            raise_err(ERR_INVALID_REQUEST, "OCC version mismatch")


def parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit out of range")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    has_more = offset + limit < total
    return sliced, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
