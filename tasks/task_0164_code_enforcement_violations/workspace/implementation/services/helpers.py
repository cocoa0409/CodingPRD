"""Shared request helpers: body parsing, field/enum validation, pagination,
path-id lookup, datetime parsing.
"""

from datetime import datetime, timezone

from flask import request

from errors import err


def get_body():
    """Parse the JSON body; default to {} when absent. Malformed JSON -> 400."""
    if request.data:
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "body must be a JSON object")
        return data
    return {}


def require_fields(body, *names):
    """Ensure each named field is present and non-null -> ERR_INVALID_REQUEST."""
    for name in names:
        if name not in body or body[name] is None:
            raise err("ERR_INVALID_REQUEST", f"missing required field: {name}")


def require_enum(body, name, allowed):
    """Field must be present and within the allowed set -> ERR_INVALID_REQUEST."""
    require_fields(body, name)
    if body[name] not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{name} must be one of {sorted(allowed)}")


def require_int(body, name):
    """Field must be present and an integer -> ERR_INVALID_REQUEST."""
    require_fields(body, name)
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")
    return val


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.
    Invalid -> ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults 10, min 1, max 100; offset defaults 0. Out-of-range values are
    clamped to the bounds. Non-integer values -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """Return the page slice. items must already be sorted."""
    return items[offset:offset + limit]


def sort_by_created(items):
    """Sort records by creation order ascending (PRD §2.3), using _seq tiebreak."""
    return sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def lookup(collection, _id):
    """Path-id lookup; missing -> ERR_NOT_FOUND (PRD §2.8)."""
    record = collection.get(_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "resource not found")
    return record


def resolve_ref(collection, _id):
    """Body FK resolution; missing -> ERR_REFERENCE_NOT_FOUND (PRD §2.8)."""
    record = collection.get(_id)
    if record is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "referenced resource does not exist")
    return record
