"""Response envelope, auth context, body validators, pagination.

Envelope per SCAFFOLD.yaml §1.0 / PRD §2.2:
  success: {"meta": {api_request_id, api_request_timestamp, [pagination]},
            "response_type": "object"|"array", "data": ...}
  error:   {"meta": {...}, "response_type": "error",
            "data": {"error_id": ..., "message": ...}}
Pagination params: limit (default 10, min 1, max 100), offset (default 0).
"""
import random
import string
from datetime import datetime

from flask import request, jsonify

import db
from errors import ApiError, ERR_MISSING_CONTEXT, ERR_FORBIDDEN, ERR_INVALID_REQUEST

ALL_ROLES = [
    "ProgramAdmin", "OperationsClerk", "Teller", "Supervisor",
    "Manager", "ComplianceOfficer", "AccountHolder",
]


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def ok(data, response_type="object", status=200, pagination=None):
    m = _meta()
    if pagination is not None:
        m.update(pagination)
    body = {"meta": m, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, status=200):
    page, pag = paginate(items)
    return ok(page, response_type="array", status=status, pagination=pag)


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


def auth():
    """Tier 1: X-User-ID and X-User-Role present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise ApiError(ERR_MISSING_CONTEXT, 400,
                       "X-User-ID and X-User-Role headers must be present and non-empty")
    return uid, role


def require_role(role, allowed):
    """Tier 2: caller role must be listed for the endpoint."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role %s is not authorized for this operation" % role)


def require_body():
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def v_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a non-empty string" % field)
    return v


def v_int(body, field, min_value=None):
    v = body.get(field)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be an integer" % field)
    if min_value is not None and v < min_value:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be >= %d" % (field, min_value))
    return v


def v_enum(body, field, members):
    v = body.get(field)
    if v not in members:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' must be one of %s" % (field, ", ".join(members)))
    return v


def parse_date_str(s):
    """Strict YYYY-MM-DD parse; returns date or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def v_date(body, field):
    v = body.get(field)
    d = parse_date_str(v)
    if d is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' must be a YYYY-MM-DD date" % field)
    return v  # keep the canonical string form


def paginate(items):
    """limit/offset query params; defaults 10/0; limit clamped to [1,100]."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit and offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def sort_created(items):
    """All lists sort by created_at ASC (PRD §2.3); seq breaks ties in creation order."""
    return sorted(items, key=lambda e: (e["created_at"], e["seq"]))
