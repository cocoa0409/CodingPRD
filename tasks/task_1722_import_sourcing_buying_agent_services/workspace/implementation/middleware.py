"""Auth header extraction, role admission, body validation, pagination."""

import re

from flask import request

from db import store
from errors import ApiError

ALL_ROLES = [
    "PlatformAdmin",
    "BuyerManager",
    "SourcingAgent",
    "FactoryRep",
    "Inspector",
    "ComplianceOfficer",
]

DELIVERY_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def require_roles(*roles):
    """Validation priorities 1-2: header presence, then role admission."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
            400,
        )
    if role not in roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not permitted on this endpoint" % role,
            403,
        )
    return uid, role


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object", 400)
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str):
        raise ApiError(
            "ERR_VALIDATION", "Missing or invalid required field: %s" % field, 400
        )
    return value


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", "Field %s must be a string" % field, 400)
    return value


def req_int(data, field, lo=None, hi=None):
    value = data.get(field)
    if not _is_int(value):
        raise ApiError(
            "ERR_VALIDATION", "Missing or invalid required field: %s" % field, 400
        )
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ApiError("ERR_VALIDATION", "Field %s is out of range" % field, 400)
    return value


def opt_int(data, field, default=None, lo=None, hi=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not _is_int(value):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % field, 400)
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ApiError("ERR_VALIDATION", "Field %s is out of range" % field, 400)
    return value


def req_enum(data, field, allowed):
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            "ERR_VALIDATION",
            "Field %s must be one of %s" % (field, ", ".join(allowed)),
            400,
        )
    return value


def req_delivery_month(data, field="delivery_month"):
    value = data.get(field)
    if not isinstance(value, str) or not DELIVERY_MONTH_RE.match(value):
        raise ApiError(
            "ERR_VALIDATION", "Field %s must be a YYYY-MM string" % field, 400
        )
    return value


def paginate(items):
    """Offset pagination per PRD §2.3: limit default 10, min 1, max 100."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit must be an integer", 400)
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "offset must be an integer", 400)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset : offset + limit]
    return page, limit, offset, total


def sorted_created(items):
    """List results sort by created_at ascending (insertion order tie-break)."""
    return sorted(items, key=lambda e: (e["_created_dt"], e["_seq"]))


def get_or_404(table, resource_id, error_id, label):
    entity = table.get(resource_id)
    if entity is None:
        raise ApiError(error_id, "%s not found: %s" % (label, resource_id), 404)
    return entity
