"""Shared parsing / validation / pagination helpers."""
from datetime import datetime, timezone

from flask import request

import db
from errors import err


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none/empty)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_int(body, field, *, required=True, minimum=None, maximum=None, gt=None,
                default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} below minimum")
    if gt is not None and not v > gt:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be > {gt}")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} above maximum")
    return v


def require_str(body, field, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return v


def require_enum(body, field, allowed, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    v = body[field]
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} has an invalid value")
    return v


def require_bool(body, field, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


def parse_dt(body, field, *, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string")
    return parse_iso(v, field)


def parse_iso(value, field="datetime"):
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        raise err("ERR_INVALID_REQUEST", f"Field {field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_pagination():
    """limit/offset query params per PRD §2.3 (defaults 10/0, min 1, max 100)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range (1..100)")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3) then slice. Returns (page, total, has_more)."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = offset + limit < total
    return page, total, has_more


def touch(record):
    """Apply a mutation: bump updated_at and version (PRD §2.4/§2.5)."""
    record["updated_at"] = db.iso_now()
    record["version"] = record.get("version", 0) + 1


def base_record(common_fields=True):
    rec = {"id": db.new_id(), "created_at": db.iso_now()}
    if common_fields:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec
