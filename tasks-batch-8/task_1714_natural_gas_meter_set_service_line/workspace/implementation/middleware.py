"""Auth header extraction, role checking, pagination, and common validation helpers.

Per PRD §2.1: every request carries X-User-ID and X-User-Role.
Ten roles: Builder, NewBusinessRep, DesignEngineer, BillingClerk,
PermitCoordinator, FieldSupervisor, MeterTechnician, Inspector, GISAnalyst,
SystemAdmin.
"""

import uuid

from flask import request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    raise_error,
)

ROLES = {
    "Builder",
    "NewBusinessRep",
    "DesignEngineer",
    "BillingClerk",
    "PermitCoordinator",
    "FieldSupervisor",
    "MeterTechnician",
    "Inspector",
    "GISAnalyst",
    "SystemAdmin",
}

ANY_ROLE = sorted(ROLES)


def actor():
    """Extract and validate the auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*roles):
    """Validate auth headers and role authorization; returns (user_id, role)."""
    user_id, role = actor()
    if role not in roles:
        raise_error(ERR_UNAUTHORIZED_ROLE, f"Role {role} is not authorized for this operation")
    return user_id, role


def new_id() -> str:
    return str(uuid.uuid4())


def get_body():
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"Invalid value for {field}: {val!r}")
    return val


def require_int(body, field, minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return val


def require_number(body, field, minimum=None, exclusive_minimum=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    if minimum is not None and val < minimum:
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    if exclusive_minimum is not None and val <= exclusive_minimum:
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be > {exclusive_minimum}")
    return val


def require_bool(body, field):
    val = body.get(field)
    if not isinstance(val, bool):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return val


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return val


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3 (default 10, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records, sort_key=None):
    """Sort by created_at ascending (default), apply pagination, return (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    items = sorted(records, key=sort_key or (lambda r: (r.get("created_at", ""), r.get("id", ""))))
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def validate_crossings(crossings, required_nonempty=False):
    """Validate a crossings array shape; returns the list."""
    if crossings is None:
        if required_nonempty:
            raise_error(ERR_INVALID_REQUEST, "crossings must be non-empty")
        return []
    if not isinstance(crossings, list):
        raise_error(ERR_INVALID_REQUEST, "crossings must be an array")
    for seg in crossings:
        if not isinstance(seg, dict):
            raise_error(ERR_INVALID_REQUEST, "each crossing segment must be an object")
        st = seg.get("surface_type")
        if st not in ("ASPHALT", "CONCRETE", "LANDSCAPE"):
            raise_error(ERR_INVALID_REQUEST, "crossing surface_type must be ASPHALT, CONCRETE, or LANDSCAPE")
        length = seg.get("length_ft")
        width = seg.get("width_ft")
        if isinstance(length, bool) or not isinstance(length, (int, float)) or length <= 0:
            raise_error(ERR_INVALID_REQUEST, "crossing length_ft must be a positive number")
        if isinstance(width, bool) or not isinstance(width, (int, float)) or width <= 0:
            raise_error(ERR_INVALID_REQUEST, "crossing width_ft must be a positive number")
    if required_nonempty and len(crossings) == 0:
        raise_error(ERR_INVALID_REQUEST, "crossings must be non-empty for ROAD_CUT permits")
    return crossings


def validate_window(start_minute, end_minute, end_max=1440):
    """Validate a minutes-from-midnight window: 0 <= start <= 1439, start < end <= 1440."""
    if isinstance(start_minute, bool) or not isinstance(start_minute, int):
        raise_error(ERR_INVALID_REQUEST, "start_minute must be an integer")
    if isinstance(end_minute, bool) or not isinstance(end_minute, int):
        raise_error(ERR_INVALID_REQUEST, "end_minute must be an integer")
    if start_minute < 0 or start_minute > 1439:
        raise_error(ERR_INVALID_REQUEST, "start_minute must be between 0 and 1439")
    if end_minute > end_max or end_minute <= start_minute:
        raise_error(ERR_INVALID_REQUEST, "end_minute must be > start_minute and <= 1440")


def parse_iso_date(value, field):
    """Parse an ISO calendar date string (YYYY-MM-DD)."""
    import datetime as _dt
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an ISO date string")
    try:
        return _dt.date.fromisoformat(value)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a valid ISO date (YYYY-MM-DD)")


# --- Application posture helpers ---

SPINE = [
    "DRAFT", "SUBMITTED", "LOAD_CONFIRMED", "DESIGN", "QUOTED", "CIAC_PENDING",
    "APPROVED_FOR_CONSTRUCTION", "PERMITTING", "CONSTRUCTION_SCHEDULED",
    "SERVICE_INSTALLED", "METER_WORK", "TESTING", "TURN_ON", "ENERGIZED",
    "GIS_REVIEW", "COMPLETED",
]
SPINE_INDEX = {s: i for i, s in enumerate(SPINE)}
APP_TERMINAL = {"COMPLETED", "REJECTED", "CANCELLED", "EXPIRED"}


def spine_at_least(app, status):
    return SPINE_INDEX[app["status"]] >= SPINE_INDEX[status]


def check_app_not_terminal(app):
    from errors import ERR_APPLICATION_TERMINAL
    if app["status"] in APP_TERMINAL:
        raise_error(ERR_APPLICATION_TERMINAL, "Application is in a terminal state")


def check_app_not_held(app):
    from errors import ERR_APPLICATION_ON_HOLD
    if app["hold_status"] != "NOT_HELD":
        raise_error(ERR_APPLICATION_ON_HOLD, "Application is on hold")


def check_app_mutable(app):
    """Terminal check precedes the hold check (PRD §2.6 step 6)."""
    check_app_not_terminal(app)
    check_app_not_held(app)
