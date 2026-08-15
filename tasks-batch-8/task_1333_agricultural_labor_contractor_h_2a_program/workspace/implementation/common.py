"""Shared plumbing: errors, response envelope, auth, pagination, dates."""

import secrets
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import g, jsonify, request

from store import db, new_id, next_seq

ALL_ROLES = [
    "ContractorAdmin",
    "GrowerRep",
    "ProgramReviewer",
    "HousingInspector",
    "VisaOfficer",
    "WageAuditor",
    "SystemAdmin",
]


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def invalid(message="invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, message)


# ---------------------------------------------------------------- clock / time

def now_dt():
    return db.clock


def clock_date():
    return db.clock.date()


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def fmt_instant(dt):
    """Clock reading: fractional digits only when present."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso():
    return fmt_ts(db.clock)


def parse_date_val(v, field="date"):
    if not isinstance(v, str):
        raise invalid(f"{field} must be an ISO date string")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise invalid(f"{field} must be a valid ISO date (YYYY-MM-DD)")


def parse_instant(v):
    if not isinstance(v, str) or not v.strip():
        raise invalid("to_iso8601 must be an ISO 8601 timestamp string")
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise invalid("to_iso8601 must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ------------------------------------------------------------------- envelope

def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_ts(db.clock),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ------------------------------------------------------------------ pagination

def paginate(items):
    """items must already be sorted by creation order; returns
    (page, total, limit, offset) applying clamped limit/offset."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise invalid("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise invalid("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset


def created_order(records):
    return sorted(records, key=lambda r: r["_seq"])


# ----------------------------------------------------------------------- auth

def auth(*roles):
    """Priorities 1-2: header presence, then role admission."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID", "")
            role = request.headers.get("X-User-Role", "")
            if uid is None or role is None or not uid.strip() or not role.strip():
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers must be present and non-empty",
                )
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED_ROLE", 403,
                    f"role {role} is not admitted to this endpoint",
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def forbid_ownership(message="caller does not own the referenced resource"):
    return ApiError("ERR_FORBIDDEN_RESOURCE_OWNERSHIP", 403, message)


# ---------------------------------------------------------------------- body

def body():
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise invalid("request body is not valid JSON")
        if not isinstance(data, dict):
            raise invalid("request body must be a JSON object")
        return data
    return {}


# ------------------------------------------------------------------ records

def stamp_new(rec):
    rec["id"] = new_id()
    ts = now_iso()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_immutable(rec):
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] += 1


# ----------------------------------------------------------------- validators

def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str):
        raise invalid(f"{name} is required and must be a string")
    return v


def opt_str(b, name, default=None):
    v = b.get(name, default)
    if v is not None and not isinstance(v, str):
        raise invalid(f"{name} must be a string")
    return v


def req_int(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid(f"{name} is required and must be an integer")
    return v


def opt_int(b, name, default=None):
    v = b.get(name, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise invalid(f"{name} must be an integer")
    return v


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        raise invalid(f"{name} is required and must be a boolean")
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise invalid(f"{name} must be one of {sorted(allowed)}")
    return v


def get_or_404(table, rid, error_id, label):
    rec = table.get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise ApiError(error_id, 404, f"{label} not found")
    return rec
