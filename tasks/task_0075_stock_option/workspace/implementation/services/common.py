"""Common helpers — version/timestamp bumping, validation utilities, pagination."""

from flask import request
from db import DB
from services.time_util import server_now, format_iso, parse_iso
from errors import (
    raise_error,
    ERR_VERSION_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)


def bump_version(row):
    """Increment version and refresh updated_at on a mutable entity."""
    row["version"] = int(row.get("version", 0)) + 1
    row["updated_at"] = format_iso(server_now())


def init_common(row):
    """Initialize created_at/updated_at/version for a mutable entity."""
    now = format_iso(server_now())
    row.setdefault("created_at", now)
    row.setdefault("updated_at", now)
    row.setdefault("version", 1)


def init_append_only(row):
    row.setdefault("created_at", format_iso(server_now()))


def check_occ(row, body):
    """If body contains 'version', it must match row.version; else skip."""
    if not isinstance(body, dict):
        return
    if "version" not in body:
        return
    supplied = body.get("version")
    if supplied is None:
        return
    if not isinstance(supplied, int):
        raise_error(ERR_INVALID_REQUEST, "version must be integer")
    if supplied != int(row.get("version", 0)):
        raise_error(ERR_VERSION_MISMATCH, "version mismatch")


def get_or_404(table, oid):
    row = DB[table].get(oid)
    if row is None:
        raise_error(ERR_NOT_FOUND, f"{table} {oid} not found")
    return row


def get_or_none(table, oid):
    return DB[table].get(oid)


def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length and request.content_length > 0:
            try:
                body = request.get_json(silent=True)
            except Exception:
                body = None
            if body is None:
                return {}
            if not isinstance(body, dict):
                raise_error(ERR_INVALID_REQUEST, "Body must be a JSON object")
            return body
        return {}
    return {}


def get_pagination():
    """Parse limit/offset query params with defaults 10/0 and bounds 1..100, >=0."""
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "limit must be integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "offset must be integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be in [1, 100]")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate_list(items, limit, offset):
    total = len(items)
    sliced = items[offset:offset + limit]
    return sliced, total


def sort_by_created_at_asc(items):
    return sorted(items, key=lambda r: r.get("created_at", ""))


def require_positive_int(body, key, allow_zero=False):
    v = body.get(key)
    if v is None or not isinstance(v, int) or isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"{key} must be a non-negative integer" if allow_zero else f"{key} must be a positive integer")
    if allow_zero and v < 0:
        raise_error(ERR_INVALID_REQUEST, f"{key} must be >= 0")
    if (not allow_zero) and v < 1:
        raise_error(ERR_INVALID_REQUEST, f"{key} must be >= 1")
    return v


def require_string(body, key):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"{key} must be a non-empty string")
    return v


def require_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"{key} must be one of {sorted(list(allowed))}")
    return v


def require_iso_datetime(body, key):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"{key} must be an ISO datetime")
    dt = parse_iso(v)
    if dt is None:
        raise_error(ERR_INVALID_REQUEST, f"{key} is not a valid ISO datetime")
    return dt
