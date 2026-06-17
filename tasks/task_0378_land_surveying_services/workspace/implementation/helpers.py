"""Shared validation, pagination, and lookup helpers."""
from flask import request

import errors
from db import store
from calculations import _parse_dt

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def get_json_body():
    """Parse JSON body; treat empty/None as empty dict."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    """Priority 4: required fields present (not None / not missing)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Invalid value for %s; must be one of %s" % (field, sorted(allowed)))


def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)


def require_number(body, field, gt=None, ge=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    if gt is not None and not (val > gt):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be > %s" % (field, gt))
    if ge is not None and not (val >= ge):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, ge))
    return val


def require_int(body, field, ge=None, gt=None):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if ge is not None and not (val >= ge):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, ge))
    if gt is not None and not (val > gt):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be > %s" % (field, gt))
    return val


def require_bool_optional(body, field):
    if field in body and body[field] is not None:
        if not isinstance(body[field], bool):
            raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)


def require_datetime(body, field):
    val = body.get(field)
    if not isinstance(val, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime string" % field)
    try:
        _parse_dt(val)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a valid ISO 8601 datetime" % field)
    return val


def lookup_or_404(table, rid):
    """Priority 3: existence; raises ERR_NOT_FOUND when missing."""
    if rid is None or rid not in table:
        raise errors.err(errors.ERR_NOT_FOUND, "Resource not found: %s" % rid)
    return table[rid]


def parse_pagination():
    """limit/offset from query (PRD §2.3). Invalid values -> ERR_INVALID_REQUEST."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_val = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_val < PAGINATION_MIN_LIMIT:
            limit_val = PAGINATION_MIN_LIMIT
        if limit_val > PAGINATION_MAX_LIMIT:
            limit_val = PAGINATION_MAX_LIMIT
    if offset is None:
        offset_val = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_val = int(offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_val < PAGINATION_MIN_OFFSET:
            offset_val = PAGINATION_MIN_OFFSET
    return limit_val, offset_val


def paginate(records, limit, offset):
    """Sort by created_at asc (PRD §2.3), then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


def crew_open_assignment_count(crew_id):
    """Computed: count of FieldAssignments for crew in {SCHEDULED, IN_PROGRESS}."""
    return sum(
        1 for a in store.field_assignments.values()
        if a["crew_member_id"] == crew_id and a["status"] in ("SCHEDULED", "IN_PROGRESS")
    )
