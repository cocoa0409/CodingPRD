"""Cross-cutting helpers: response envelope, error catalog, auth/RBAC/ownership,
request-body validation, pagination."""
import random
import string
from datetime import datetime, timezone

from flask import request, jsonify

import db

# ---------------------------------------------------------------------------
# Error catalog (id -> HTTP status)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_PREFERENCE_CLAIM_NOT_FOUND": 404,
    "ERR_WAITLIST_NOT_FOUND": 404,
    "ERR_WAITLIST_ENTRY_NOT_FOUND": 404,
    "ERR_UNIT_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_TENANCY_NOT_FOUND": 404,
    "ERR_CERTIFICATION_NOT_FOUND": 404,
    "ERR_INTERIM_CHANGE_NOT_FOUND": 404,
    "ERR_GRIEVANCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_UNIT_NOT_AVAILABLE": 409,
    "ERR_TENANCY_NOT_ACTIVE": 409,
    "ERR_WAITLIST_CLOSED": 409,
    "ERR_BEDROOM_MISMATCH": 422,
    "ERR_OFFER_EXPIRED": 409,
    "ERR_UNIT_TURNOVER_CONFLICT": 409,
    "ERR_CERT_PERIOD_OVERLAP": 409,
    "ERR_OVER_INCOME": 422,
}

ROLES = {"IntakeClerk", "HousingSpecialist", "PropertyManager", "Applicant"}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": _timestamp()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Authentication / Authorization / Ownership
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this operation")


def require_ownership(role, uid, owner_applicant_id):
    """For the entity-backed Applicant role, enforce that it owns the resource."""
    if role == "Applicant" and uid != owner_applicant_id:
        raise ApiError("ERR_UNAUTHORIZED", "applicant does not own this resource")


# ---------------------------------------------------------------------------
# Body / query validation helpers
# ---------------------------------------------------------------------------
def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def need_str(data, key, allow_empty=False):
    v = data.get(key)
    if v is None:
        raise ApiError("ERR_VALIDATION", f"{key} is required")
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise ApiError("ERR_VALIDATION", f"{key} must be a non-empty string")
    return v


def need_enum(data, key, allowed):
    v = need_str(data, key)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", f"{key} must be one of {sorted(allowed)}")
    return v


def opt_enum(data, key, allowed, default=None):
    if key not in data or data.get(key) is None:
        return default
    return need_enum(data, key, allowed)


def need_int(data, key):
    v = data.get(key)
    if v is None:
        raise ApiError("ERR_VALIDATION", f"{key} is required")
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", f"{key} must be an integer")
    return v


def opt_int_nonneg(data, key, default=0):
    if key not in data or data.get(key) is None:
        return default
    v = data.get(key)
    if not _is_int(v) or v < 0:
        raise ApiError("ERR_VALIDATION", f"{key} must be a non-negative integer")
    return v


def need_int_in(data, key, lo, hi):
    v = need_int(data, key)
    if v < lo or v > hi:
        raise ApiError("ERR_VALIDATION", f"{key} must be between {lo} and {hi}")
    return v


def opt_bool(data, key, default=False):
    if key not in data or data.get(key) is None:
        return default
    v = data.get(key)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"{key} must be a boolean")
    return v


def parse_iso(s, key="datetime"):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", f"{key} must be an ISO-8601 string")
    try:
        t = s.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
    except Exception:
        raise ApiError("ERR_VALIDATION", f"{key} must be a valid ISO-8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def need_dt(data, key):
    v = data.get(key)
    if v is None:
        raise ApiError("ERR_VALIDATION", f"{key} is required")
    return parse_iso(v, key)


# ---------------------------------------------------------------------------
# Pagination (limit default 10 / min 1 / max 100; offset default 0)
# ---------------------------------------------------------------------------
def pagination():
    limit = _parse_qint("limit", 10)
    offset = _parse_qint("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_qint(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", f"{name} must be an integer")


def opt_qint(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", f"{name} must be an integer")


# ---------------------------------------------------------------------------
# Existence resolution (path/body FK -> record, or 404)
# ---------------------------------------------------------------------------
def get_or_404(store, rid, error_id):
    rec = store.get(rid)
    if rec is None:
        raise ApiError(error_id)
    return rec


def owner_applicant_id(kind, rec):
    """Resolve the owning applicant id for ownership checks."""
    if kind == "applicant":
        return rec["id"]
    if kind in ("member", "preference_claim", "waitlist_entry", "tenancy"):
        return rec["applicant_id"]
    if kind == "offer":
        entry = db.waitlist_entries.get(rec["waitlist_entry_id"])
        return entry["applicant_id"] if entry else None
    if kind in ("certification", "interim_change", "grievance"):
        ten = db.tenancies.get(rec["tenancy_id"])
        return ten["applicant_id"] if ten else None
    return None
