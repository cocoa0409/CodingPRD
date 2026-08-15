"""Response envelope, pagination, auth context, and request validation helpers."""

from flask import jsonify, request

from db import (
    STORE, fmt_ts, new_request_id, now,
    parse_dt, parse_date, is_int, is_bool, is_num,
)
from errors import err

ROLES = {
    "SchoolAdmin", "Student", "Parent", "Guardian",
    "DormParent", "Nurse", "Dean", "FrontDesk",
}

STAFF_ROLE_FOR = {
    "DormParent": "DORM_PARENT",
    "Nurse": "NURSE",
    "Dean": "DEAN",
    "FrontDesk": "FRONT_DESK",
}

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _meta(pagination=None):
    m = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }
    if pagination:
        m.update(pagination)
    return m


def success_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def success_list(items, total_count, limit, offset, code=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_response(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    resp = jsonify(body)
    resp.status_code = api_err.http_status
    return resp


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    args = request.args
    try:
        limit = int(args.get("limit", PAGE_DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = PAGE_DEFAULT_LIMIT
    try:
        offset = int(args.get("offset", PAGE_DEFAULT_OFFSET))
    except (TypeError, ValueError):
        offset = PAGE_DEFAULT_OFFSET
    if limit < PAGE_MIN_LIMIT:
        limit = PAGE_MIN_LIMIT
    if limit > PAGE_MAX_LIMIT:
        limit = PAGE_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def sort_and_paginate(records):
    """Sort by (created_at, creation seq) ascending and slice per query params."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda e: (e.get("created_at") or now(), e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total, limit, offset


def list_response(records, serializer):
    page, total, limit, offset = sort_and_paginate(records)
    return success_list([serializer(e) for e in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "Missing or invalid X-User-Role / X-User-ID headers")
    return Actor(user_id, role)


def require_roles(actor, allowed):
    """Priority 2 (role membership)."""
    if actor.role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s is not permitted on this endpoint" % actor.role)


def staff_identity(actor, expected_staff_role):
    """Resolve X-User-ID to a StaffMember whose staff_role matches the role."""
    member = STORE["staff"].get(actor.user_id)
    if member is None or member["staff_role"] != expected_staff_role:
        raise err("ERR_FORBIDDEN",
                  "X-User-ID does not identify an acting %s" % expected_staff_role)
    return member


def resolve_identity(actor):
    """For staff-backed roles resolve (but do not require) the StaffMember."""
    if actor.role in STAFF_ROLE_FOR:
        member = STORE["staff"].get(actor.user_id)
        if member is not None and member["staff_role"] == STAFF_ROLE_FOR[actor.role]:
            return member
        return None
    return None


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err("ERR_MISSING_REQUIRED_FIELD", "Request body must be a JSON object")
    return data


def req_string(body, field):
    v = body.get(field)
    if v is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: %s" % field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be a non-empty string" % field)
    return v


def opt_string(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if v is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: %s" % field)
    if not is_int(v):
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be an integer" % field)
    return v


def opt_int(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not is_int(v):
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be an integer" % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if v is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: %s" % field)
    if not is_bool(v):
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be a boolean" % field)
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not is_bool(v):
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be a boolean" % field)
    return v


def req_number(body, field):
    v = body.get(field)
    if v is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: %s" % field)
    if not is_num(v):
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be a number" % field)
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: %s" % field)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_FIELD_VALUE",
                  "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def req_datetime(body, field):
    """Required ISO datetime; returns (raw_string, parsed_utc_datetime)."""
    raw = body.get(field)
    if raw is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: %s" % field)
    dt = parse_dt(raw)
    if dt is None:
        raise err("ERR_MISSING_REQUIRED_FIELD",
                  "Field %s must be an ISO 8601 datetime" % field)
    return raw, dt


def opt_datetime(body, field):
    raw = body.get(field)
    if raw is None:
        return None, None
    dt = parse_dt(raw)
    if dt is None:
        raise err("ERR_MISSING_REQUIRED_FIELD",
                  "Field %s must be an ISO 8601 datetime" % field)
    return raw, dt


def req_date(body, field):
    raw = body.get(field)
    if raw is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Missing required field: %s" % field)
    d = parse_date(raw)
    if d is None:
        raise err("ERR_MISSING_REQUIRED_FIELD", "Field %s must be an ISO date" % field)
    return raw, d


def check_fk(body, field, collection):
    """Priority 3: a present (non-null) FK field must resolve."""
    v = body.get(field)
    if v is not None:
        if not isinstance(v, str) or v not in STORE[collection]:
            raise err("ERR_NOT_FOUND", "Referenced %s does not exist" % field)
    return v


def get_or_404(collection, entity_id, label="resource"):
    entity = STORE[collection].get(entity_id)
    if entity is None:
        raise err("ERR_NOT_FOUND", "No such %s: %s" % (label, entity_id))
    return entity
