"""Shared utilities: ids, timestamps, pagination, payload validation, serialization."""
import uuid
from datetime import datetime, timezone

from flask import request

from errors import raise_error
from services.clock import format_iso, now_iso


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    """Attach common system fields to a freshly created entity."""
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def get_json_body():
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    if not request.is_json:
        raise_error("ERR_INVALID_REQUEST", "Request body must be JSON")
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise_error("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise_error("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def req_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a string")
    return v


def req_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(body, field, default=None, minimum=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {minimum}")
    return v


def req_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a number")
    return float(v)


def opt_number(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a number")
    return float(v)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a boolean")
    return v


def opt_bool(body, field, default=False):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an array")
    return v


def req_datetime(body, field, parse_fn):
    v = body.get(field)
    if not isinstance(v, str):
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an ISO 8601 datetime string")
    dt = parse_fn(v)
    if dt is None:
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a valid ISO 8601 datetime")
    return dt


def get_pagination():
    """Read limit/offset query params per scaffold pagination fields and defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise_error("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise_error("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0")
    return limit, offset


def apply_filters(items, filters):
    """filters: list of (entity_field, query_value). Equality match on string form."""
    out = items
    for field, value in filters:
        if value is None:
            continue
        out = [e for e in out if _matches(e.get(field), value)]
    return out


def _matches(field_value, query_value):
    if field_value is None:
        return False
    if isinstance(field_value, bool):
        return str(field_value).lower() == query_value.lower()
    if isinstance(field_value, int):
        try:
            return field_value == int(query_value)
        except ValueError:
            return False
    return str(field_value) == query_value


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def sorted_by_created(items):
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
