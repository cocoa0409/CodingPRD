"""Shared helpers: entity CRUD plumbing, serialization, pagination, validation."""

import uuid
from datetime import datetime, timezone, date

from flask import request

import errors
from response import now_iso


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Refresh updated_at and bump version on mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1


def stamp_new(entity):
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    return entity


def get_body():
    """Parse JSON body; must be an object if present. Returns dict (possibly empty)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}")
    return body[name]


def opt_field(body, name, default=None):
    v = body.get(name, default)
    return default if v is None else v


def as_string(v, name):
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {name} must be a string")
    return v


def as_int(v, name):
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    return v


def as_number(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            f"Field {name} must be one of: {', '.join(sorted(allowed))}"
        )
    return v


def as_array(v, name):
    if not isinstance(v, list):
        raise errors.invalid_request(f"Field {name} must be an array")
    return v


def as_enum_array(v, name, allowed):
    arr = as_array(v, name)
    for item in arr:
        if not isinstance(item, str) or item not in allowed:
            raise errors.invalid_request(
                f"Field {name} items must be one of: {', '.join(sorted(allowed))}"
            )
    return arr


def parse_iso_datetime(v, name):
    """Parse an ISO8601 datetime to an aware datetime (UTC assumed when naive)."""
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {name} must be an ISO8601 string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"Field {name} must be an ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(v, name):
    """Parse an ISO8601 date (YYYY-MM-DD) to a date object."""
    if not isinstance(v, str):
        raise errors.invalid_request(f"Field {name} must be an ISO8601 date string")
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        raise errors.invalid_request(f"Field {name} must be an ISO8601 date (YYYY-MM-DD)")


def pagination_params():
    """Read limit/offset query params with defaults and bounds from the scaffold."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items pre-sorted (created_at ASC); returns (page, total_count)."""
    total = len(items)
    return items[offset: offset + limit], total


def filter_exact(items, field, value):
    if value is None:
        return items
    return [i for i in items if i.get(field) == value]


def sort_by_created(items):
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
