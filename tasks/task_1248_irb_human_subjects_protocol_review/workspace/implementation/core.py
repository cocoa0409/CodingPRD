"""Core helpers: response envelope, logical clock, pagination, auth, validation."""

import re
import uuid
from datetime import datetime, timezone

from flask import request

from errors import (
    ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_VALIDATION,
    ERR_INVESTIGATOR_NOT_FOUND, ERR_MEMBER_NOT_FOUND, ERR_PROTOCOL_NOT_FOUND,
    ERR_CONSENT_DOC_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_DECLARATION_NOT_FOUND, ERR_MEETING_NOT_FOUND,
    ERR_AGENDA_ITEM_NOT_FOUND, ERR_MODIFICATION_NOT_FOUND, ERR_CR_NOT_FOUND,
    ERR_AE_NOT_FOUND, ERR_CASE_NOT_FOUND, ERR_RELIANCE_NOT_FOUND,
)

ROLES = {
    "PrincipalInvestigator", "Reviewer", "IrbChair",
    "IrbCoordinator", "IrbAdmin", "ComplianceOfficer",
}

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_START = "2026-05-01T00:00:00Z"
_clock_now = datetime(2026, 5, 1, tzinfo=timezone.utc)


def now():
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt


def reset_clock():
    global _clock_now
    _clock_now = datetime(2026, 5, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Time parsing / formatting
# ---------------------------------------------------------------------------

def parse_iso(value, field):
    """Parse an ISO8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be an ISO8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' is not a valid ISO8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def make_meta(extra=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_iso(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def success_object(data, status=200):
    return {
        "meta": make_meta(),
        "response_type": "object",
        "data": data,
    }, status


def success_list(items, limit, offset, total_count):
    meta = make_meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }, 200


def error_body(error_id, message):
    return {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows, serializer, sort_key=None):
    rows = list(rows)
    if sort_key is not None:
        rows.sort(key=sort_key)
    else:
        rows.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(rows)
    limit, offset = pagination_params()
    page = rows[offset:offset + limit]
    return success_list([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or unrecognized X-User-ID / X-User-Role")
    return Caller(user_id, role)


def require_role(caller, *roles):
    """Priority 2: role permission for endpoint."""
    if caller.role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")


def require_chair(caller):
    """IrbChair endpoint: caller's member must exist with is_chair true."""
    import db
    require_role(caller, "IrbChair")
    member = db.irb_members.get(caller.user_id)
    if member is None or not member.get("is_chair"):
        raise ApiError(ERR_FORBIDDEN, 403,
                       "IrbChair role requires an IRB member with is_chair true")
    return member


# ---------------------------------------------------------------------------
# Existence helpers (left-to-right path resolution)
# ---------------------------------------------------------------------------

NOT_FOUND = {
    "investigator": (ERR_INVESTIGATOR_NOT_FOUND, "investigator"),
    "member": (ERR_MEMBER_NOT_FOUND, "member"),
    "protocol": (ERR_PROTOCOL_NOT_FOUND, "protocol"),
    "consent": (ERR_CONSENT_DOC_NOT_FOUND, "consent document"),
    "assignment": (ERR_ASSIGNMENT_NOT_FOUND, "review assignment"),
    "declaration": (ERR_DECLARATION_NOT_FOUND, "conflict declaration"),
    "meeting": (ERR_MEETING_NOT_FOUND, "board meeting"),
    "agenda_item": (ERR_AGENDA_ITEM_NOT_FOUND, "agenda item"),
    "modification": (ERR_MODIFICATION_NOT_FOUND, "modification"),
    "cr": (ERR_CR_NOT_FOUND, "continuing review"),
    "ae": (ERR_AE_NOT_FOUND, "adverse event report"),
    "case": (ERR_CASE_NOT_FOUND, "non-compliance case"),
    "reliance": (ERR_RELIANCE_NOT_FOUND, "reliance agreement"),
}


def get_or_404(table, rid, kind):
    row = table.get(rid)
    if row is None:
        err_id, label = NOT_FOUND[kind]
        raise ApiError(err_id, 404, f"No {label} with id {rid}")
    return row


# ---------------------------------------------------------------------------
# Request-body validation helpers
# ---------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def req_string(data, field):
    v = data.get(field)
    if v is None:
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field '{field}'")
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a non-empty string")
    return v


def opt_string(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a string")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v is None:
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field '{field}'")
    if v not in allowed:
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field)
    if v is None:
        return default
    if v not in allowed:
        raise ApiError(ERR_VALIDATION, 400,
                       f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a boolean")
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be a boolean")
    return v


def req_int(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be an integer")
    return v


def opt_int(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, f"Field '{field}' must be an integer")
    return v


def req_iso(data, field):
    v = data.get(field)
    if v is None:
        raise ApiError(ERR_VALIDATION, 400, f"Missing required field '{field}'")
    return parse_iso(v, field)


# ---------------------------------------------------------------------------
# Record factory (common fields)
# ---------------------------------------------------------------------------

def new_record(fields):
    ts = fmt_iso(now())
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec.update(fields)
    return rec


def touch(rec):
    rec["updated_at"] = fmt_iso(now())
    rec["version"] = rec.get("version", 1) + 1
