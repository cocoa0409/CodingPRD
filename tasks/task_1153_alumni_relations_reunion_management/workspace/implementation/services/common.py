"""Shared helpers: ids, timestamps, versioning, pagination, body validation."""

import uuid
from datetime import datetime, timezone

from flask import request

import db
from errors import err_invalid_request


def new_id():
    return str(uuid.uuid4())


def logical_ts():
    """Current logical-clock timestamp as ISO 8601 UTC with 3 fractional digits."""
    return format_ts(db.logical_now())


def format_ts(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime; returns aware datetime or raises 400."""
    if not isinstance(value, str):
        raise err_invalid_request("Expected ISO 8601 datetime string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_invalid_request(f"Invalid ISO 8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity):
    """Refresh updated_at and bump version on any mutation (direct or cascade)."""
    entity["updated_at"] = logical_ts()
    entity["version"] = entity.get("version", 1) + 1


def new_entity(extra):
    """Mint common system fields onto a new entity dict."""
    now = logical_ts()
    base = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    base.update(extra)
    return base


def json_body(required=None, optional=None, allow_query=False):
    """Extract JSON body; validate required fields present and no None for them.
    Returns dict. Raises ERR_INVALID_REQUEST on malformed body or missing field.

    When ``allow_query`` is true and no JSON body was sent, fall back to the
    query string — clients conventionally pass DELETE payloads as query
    parameters rather than a JSON body.
    """
    data = request.get_json(silent=True)
    if data is None:
        if allow_query and request.args:
            data = dict(request.args)
        elif required:
            raise err_invalid_request("Request body must be JSON")
        else:
            data = {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    for f in (required or []):
        if f not in data or data[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")
    return data


def pagination_args():
    """Read limit/offset query params per §2.3 defaults (limit 10, min 1, max 100, offset 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err_invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err_invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def apply_pagination(rows, limit, offset):
    """Sort by created_at ascending then slice."""
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(ordered)
    return ordered[offset:offset + limit], total


def req_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"Field {field} must be an integer")
    return value


def req_str(value, field):
    if not isinstance(value, str):
        raise err_invalid_request(f"Field {field} must be a string")
    return value


def req_enum(value, field, allowed):
    if value not in allowed:
        raise err_invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return value
