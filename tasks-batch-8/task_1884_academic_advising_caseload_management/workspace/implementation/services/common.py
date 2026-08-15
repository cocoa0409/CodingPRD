"""Shared helpers: IDs, timestamps, parsing, common fields, pagination."""
import uuid
from datetime import datetime, timezone

from flask import request

import errors
from errors import ApiError


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with three fractional digits for created_at/updated_at.

    Resource timestamps read the server-side logical clock (PRD §2.4) so that
    every time-dependent value — created_at, updated_at, due_at, checked_in_at —
    is deterministic under the test-driving clock and never wall-clock time.
    """
    import db
    logical = parse_iso_datetime(db.get_logical_clock_iso())
    return logical.strftime("%Y-%m-%dT%H:%M:%S.") + f"{logical.microsecond // 1000:03d}Z"


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime string to an aware datetime. Raises ERR_VALIDATION."""
    if not isinstance(value, str):
        raise ApiError(errors.ERR_VALIDATION, f"Datetime must be a string, got {type(value).__name__}", 400)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_VALIDATION, f"Unparseable datetime: {value}", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits and Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_new(record):
    """Set id, created_at, updated_at, version on a new record dict."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Bump updated_at and version on an existing record."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def get_pagination_params():
    """Read limit/offset query params per response_envelope pagination_defaults."""
    limit_raw = request.args.get("limit", None)
    offset_raw = request.args.get("offset", None)
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_VALIDATION, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_VALIDATION, "limit must be between 1 and 100", 400)
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_VALIDATION, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(errors.ERR_VALIDATION, "offset must be >= 0", 400)
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC then slice. Returns (page, total_count)."""
    items_sorted = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, total


def body():
    """Return parsed JSON body (empty dict for missing/empty body)."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError(errors.ERR_VALIDATION, "Request body must be valid JSON", 400)
    if not isinstance(data, dict):
        raise ApiError(errors.ERR_VALIDATION, "Request body must be a JSON object", 400)
    return data


def require_fields(data, fields):
    """Ensure required fields are present (not missing)."""
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError(errors.ERR_VALIDATION, f"Missing required field: {f}", 400)


def require_enum(value, allowed, field_name):
    if value not in allowed:
        raise ApiError(errors.ERR_VALIDATION, f"Invalid value for {field_name}: {value}", 400)
    return value
