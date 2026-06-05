"""Auth, RBAC, body validation, and pagination helpers."""
from flask import request

from errors import ApiError
from store import db


ROLES = {"Applicant", "PermitClerk", "PlanReviewer", "Inspector", "BuildingOfficial"}


def authenticate():
    """Priority 1: both headers present and X-User-Role is a known role.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2: acting role must be in the allowed set for the operation."""
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")


def get_json_body():
    """Parse JSON body; tolerate empty body as {}."""
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# ---- typed body field readers (priority 4: ERR_INVALID_REQUEST) ----
def require_str(body, field):
    val = body.get(field, None)
    if not isinstance(val, str) or val == "":
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid field: %s" % field)
    return val


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field must be a string: %s" % field)
    return val


def require_enum(body, field, choices):
    val = require_str(body, field)
    if val not in choices:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid value for %s" % field)
    return val


def opt_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in choices:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid value for %s" % field)
    return val


def _is_number(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def require_number(body, field, minimum=None, gt=None):
    val = body.get(field, None)
    if not _is_number(val):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid number: %s" % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    if gt is not None and not (val > gt):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be > %s" % (field, gt))
    return val


def opt_number(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not _is_number(val):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid number: %s" % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return val


def require_int(body, field, minimum=None):
    val = body.get(field, None)
    if not isinstance(val, int) or isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid integer: %s" % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return val


def opt_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, int) or isinstance(val, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid integer: %s" % field)
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s" % (field, minimum))
    return val


def require_datetime(body, field):
    from store import parse_ts

    val = body.get(field, None)
    if not isinstance(val, str):
        raise ApiError("ERR_INVALID_REQUEST", "Missing or invalid datetime: %s" % field)
    try:
        parse_ts(val)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "Invalid datetime: %s" % field)
    return val


# ---- pagination (priority N/A; defaults from PRD §2.3) ----
def get_pagination():
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    """rows: list already sorted ascending by creation. Returns (page, total)."""
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, total


def sort_by_creation(records):
    """Ascending by (created_at, sequence)."""
    return sorted(records, key=lambda r: (r["_created_at"], r["_seq"]))


# ---- existence lookups (priority 3) ----
_NOT_FOUND = {
    "permits": "ERR_PERMIT_NOT_FOUND",
    "contractors": "ERR_CONTRACTOR_NOT_FOUND",
    "jurisdictions": "ERR_JURISDICTION_NOT_FOUND",
    "plan_reviews": "ERR_REVIEW_NOT_FOUND",
    "correction_notices": "ERR_CORRECTION_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "inspection_slots": "ERR_SLOT_NOT_FOUND",
    "stop_work_orders": "ERR_SWO_NOT_FOUND",
    "certificates": "ERR_CO_NOT_FOUND",
    "plan_reviewers": "ERR_REVIEW_NOT_FOUND",
    "inspectors": "ERR_INSPECTION_NOT_FOUND",
}


def lookup(collection_name, rid, error_id=None):
    coll = getattr(db, collection_name)
    rec = coll.get(rid)
    if rec is None:
        raise ApiError(error_id or _NOT_FOUND[collection_name])
    return rec
