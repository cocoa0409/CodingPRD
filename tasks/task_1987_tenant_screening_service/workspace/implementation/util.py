"""Shared helpers: timestamps, serialization, request validation, pagination."""

import uuid
from datetime import datetime, timezone

from flask import request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def clock():
    return store.clock


def fmt_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string; ERR_INVALID_REQUEST on failure."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an ISO 8601 string", 400)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' is not a valid ISO 8601 datetime", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------

def get_body():
    """Return the JSON request body as a dict; ERR_INVALID_REQUEST otherwise."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def req_string(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    if not isinstance(v, str) or not v.strip():
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a non-empty string", 400)
    return v


def opt_string(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a string", 400)
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer", 400)
    return v


def opt_int(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be an integer", 400)
    return v


def req_number(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a number", 400)
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be a boolean", 400)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: {field}", 400)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{field}' must be one of {sorted(allowed)}", 400)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3 / scaffold response_envelope.pagination_*)
# ---------------------------------------------------------------------------

def pagination_params():
    """Read limit/offset query params with defaults; ERR_INVALID_REQUEST out of range."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, "Query parameter 'limit' must be between 1 and 100", 400)
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "Query parameter 'offset' must be >= 0", 400)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def stamp_new(entity, with_common=True):
    """Assign id/created_at/updated_at/version to a new entity dict."""
    entity["id"] = new_id()
    now = clock()
    entity["created_at"] = now
    if with_common:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = clock()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serializers (datetime objects -> ISO strings)
# ---------------------------------------------------------------------------

_DT_FIELDS = {
    "suspended_at", "effective_from", "effective_to", "published_at",
    "dob", "consent_signed_at", "submitted_at", "decided_at",
    "delivered_at", "last_delivered_at", "record_date", "issued_at",
    "dispute_deadline", "rescinded_at", "filed_at", "reinvestigation_deadline",
    "resolved_at", "run_at",
}


def serialize(entity):
    """Return a JSON-safe copy of an entity dict."""
    out = {}
    for k, v in entity.items():
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, list):
            out[k] = list(v)
        else:
            out[k] = v
    return out


def serialize_audit(entity):
    out = serialize(entity)
    # ConsistencyAuditRun has no updated_at / version (immutable event record)
    out.pop("updated_at", None)
    out.pop("version", None)
    return out
