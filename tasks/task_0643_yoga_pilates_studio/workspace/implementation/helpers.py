"""Request-parsing, pagination, and lookup helpers."""
from flask import request

from db import store
from errors import err
from clock import parse_iso


def get_json_body():
    """Return the request JSON body as a dict, or {} when absent/empty.

    A body that is present but not a JSON object is ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
    return data


def parse_pagination():
    """Parse limit/offset query params. limit default 10 (1..100), offset default 0 (>=0)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range (1..100)")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (stable by insertion seq) and slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return val


def require_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return val


def require_datetime(body, field):
    raw = body.get(field)
    if not isinstance(raw, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string")
    try:
        return parse_iso(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a valid ISO 8601 UTC instant")


# ---- Existence lookups (ERR_NOT_FOUND on miss) ----

def find_or_404(collection, rid, label="resource"):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", f"{label} not found")
    return rec
