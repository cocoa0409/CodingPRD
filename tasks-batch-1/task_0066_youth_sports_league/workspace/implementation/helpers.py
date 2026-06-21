"""Shared request parsing, validation, and pagination helpers."""
from flask import request

from errors import err
from store import new_id, now_iso


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return v


def optional_int(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field)


def paginate():
    """Read limit/offset query params with defaults 10/0, min/max 1/100, offset min 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def apply_pagination(items, limit, offset):
    """items is the full sorted list; returns the page slice."""
    return items[offset:offset + limit]


def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(record):
    """Refresh updated_at and bump version by 1 (a mutation)."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1
