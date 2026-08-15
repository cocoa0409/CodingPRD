"""Auth header extraction, role checking, body parsing and field validators.

Validation pipeline order (PRD section 2.8):
  1. authentication (headers)          -> ERR_UNAUTHENTICATED 401
  2. request shape                     -> ERR_INVALID_REQUEST 400
  3. authorization (role on endpoint)  -> ERR_UNAUTHORIZED 403
  4. existence (path ids then FKs)     -> ERR_NOT_FOUND 404
  ... then business stages handled in route handlers / services.
"""

from datetime import datetime

from flask import request

import errors
from db import parse_iso

ROLES = ("DistributorAdmin", "RouteDriver", "WarehouseOperator")


def authenticate():
    """Stage 1: both headers present, role within the declared set."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role == "" or user_id == "":
        raise errors.unauthenticated()
    if role not in ROLES:
        raise errors.unauthenticated()
    return role


def require_roles(role, allowed):
    """Stage 3: acting role permitted on the endpoint."""
    if role not in allowed:
        raise errors.unauthorized()


def json_body(required=True):
    """Parse the JSON request body. Missing/invalid JSON -> 400 when required."""
    if request.data is None or request.data == b"":
        if required:
            raise errors.invalid_request("Request body must be a JSON object")
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise errors.invalid_request("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Shape-check field helpers (all raise ERR_INVALID_REQUEST / 400 on type errors)
# ---------------------------------------------------------------------------

def need(body, field):
    if field not in body:
        raise errors.invalid_request("Required field missing: %s" % field)
    return body[field]


def as_str(v, field):
    if not isinstance(v, str) or isinstance(v, bool):
        raise errors.invalid_request("Field %s must be a string" % field)
    return v


def as_int(v, field):
    if not isinstance(v, int) or isinstance(v, bool):
        raise errors.invalid_request("Field %s must be an integer" % field)
    return v


def as_bool(v, field):
    if not isinstance(v, bool):
        raise errors.invalid_request("Field %s must be a boolean" % field)
    return v


def as_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise errors.invalid_request(
            "Field %s must be one of {%s}" % (field, ", ".join(allowed))
        )
    return v


def as_str_list(v, field):
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise errors.invalid_request("Field %s must be an array of strings" % field)
    return v


def as_dt(v, field):
    """Validate an ISO 8601 datetime string; returns the raw string for echo."""
    if not isinstance(v, str):
        raise errors.invalid_request("Field %s must be an ISO 8601 datetime string" % field)
    try:
        parse_iso(v)
    except (ValueError, TypeError):
        raise errors.invalid_request("Field %s must be an ISO 8601 datetime string" % field)
    return v


def pagination_params():
    """limit / offset query params: default 10 / 0, bounds 1..100 / >=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("offset must be zero or positive")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted in creation order."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
