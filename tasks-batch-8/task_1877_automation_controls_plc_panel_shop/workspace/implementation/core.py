"""Core primitives: errors, response envelope, auth, time, validation helpers."""

import random
import re
import string
from datetime import datetime, timedelta, timezone

from flask import request

from store import db

# ---------------------------------------------------------------------------
# Errors (error ids + HTTP statuses from the scaffold error catalog)
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or malformed X-User-Role / X-User-ID headers."):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized(msg="Role not permitted on this endpoint."):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_owner(msg="Customer identity does not match the owning chain."):
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403, msg)


def err_not_found(msg="Resource not found."):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_ref_not_found(msg="Body-referenced foreign key does not exist."):
    return ApiError("ERR_REFERENCE_NOT_FOUND", 404, msg)


def err_invalid_state(msg="Target entity not in a state from which the requested transition is defined."):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale(msg="OCC expected version does not match the parent's current version."):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_sod(msg="Approver/verifier is the same user as the designer/requester."):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403, msg)


def err_sccr(msg="Panel SCCR is below the 5 kA minimum."):
    return ApiError("ERR_SCCR_BELOW_MINIMUM", 422, msg)


def err_downrated(msg="Substitution would lower the panel SCCR chain."):
    return ApiError("ERR_SUBSTITUTION_DOWNRATED", 422, msg)


def err_outside_window(msg="Startup begin outside the scheduled window."):
    return ApiError("ERR_OUTSIDE_SCHEDULED_WINDOW", 422, msg)


def err_warranty_expired(msg="Claim filed or triaged past warranty expiry, or job not commissioned."):
    return ApiError("ERR_WARRANTY_EXPIRED", 422, msg)


def err_double_booked(msg="Engineer already has an overlapping session."):
    return ApiError("ERR_ENGINEER_DOUBLE_BOOKED", 422, msg)


def err_turnover(msg="Panel turnover buffer violated."):
    return ApiError("ERR_PANEL_TURNOVER_VIOLATION", 422, msg)


def err_inactive(msg="Referenced component is inactive."):
    return ApiError("ERR_COMPONENT_INACTIVE", 422, msg)


def err_duplicate(msg="Uniqueness violation."):
    return ApiError("ERR_DUPLICATE", 409, msg)


def err_credit_hold(msg="Customer credit hold blocks this operation."):
    return ApiError("ERR_CREDIT_HOLD", 402, msg)


def err_invalid_request(msg="Missing/invalid required field, out-of-range value, or enum violation."):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_inadmissible(msg="Claim against a job with no commissioned panel, or negative labor hours."):
    return ApiError("ERR_CLAIM_INADMISSIBLE", 422, msg)


def err_remote(msg="REMOTE support mode requires remote_access_granted."):
    return ApiError("ERR_REMOTE_ACCESS_REQUIRED", 422, msg)


def err_undecided(msg="Test points undecided or result recorded on non-UNTESTED point / non-OPEN session."):
    return ApiError("ERR_TEST_POINTS_UNDECIDED", 422, msg)


def err_panel_not_ready(msg="Panel precondition for the requested gate failed."):
    return ApiError("ERR_PANEL_NOT_READY", 409, msg)


def err_job_gate(msg="Job-level gate failed."):
    return ApiError("ERR_JOB_GATE_BLOCKED", 409, msg)


def err_backup(msg="No RELEASED ProgramVersion with site_backup_taken == true."):
    return ApiError("ERR_BACKUP_REQUIRED", 422, msg)


def err_bad_body(msg="Malformed JSON body or wrong top-level type."):
    return ApiError("ERR_INVALID_REQUEST_BODY", 400, msg)


# ---------------------------------------------------------------------------
# Logical clock helpers (PRD 2.5)
# ---------------------------------------------------------------------------


def now_dt():
    """Current logical time as a datetime."""
    return db.clock


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (
        dt.astimezone(timezone.utc).microsecond // 1000
    )


def now_iso():
    return iso(now_dt())


def parse_iso(s):
    """Parse an ISO 8601 string ('Z' or numeric offset) into an aware datetime."""
    if not isinstance(s, str):
        raise err_invalid_request("Expected an ISO 8601 timestamp string.")
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise err_invalid_request("Malformed ISO 8601 timestamp: %r" % s)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add calendar months with day clamping."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    if m == 12:
        last = 31
    elif m in (4, 6, 9, 11):
        last = 30
    else:
        last = 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
    d = min(dt.day, last)
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Response envelope (scaffold section 1.0)
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_iso(),
    }


def envelope_object(data, code=200):
    return {"meta": _meta(), "response_type": "object", "data": data}, code


def envelope_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + limit) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, 200


def envelope_error(api_err):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }, api_err.http_status


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, validations priority 1-3)
# ---------------------------------------------------------------------------

ROLES = {
    "ProjectManager",
    "QAManager",
    "DesignEngineer",
    "ShopLead",
    "TestTechnician",
    "ControlsEngineer",
    "FieldEngineer",
    "ShippingClerk",
    "Customer",
}


def auth_context():
    """Validate X-User-ID / X-User-Role; returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*roles):
    user_id, role = auth_context()
    if role not in roles:
        raise err_unauthorized()
    return user_id, role


# ---------------------------------------------------------------------------
# Request body parsing and field validation
# ---------------------------------------------------------------------------


def get_body(required=False):
    """Parse the JSON body.

    Missing/empty body returns {} (endpoints with required fields then fail
    with ERR_INVALID_REQUEST). Malformed JSON or a non-object top level raises
    ERR_INVALID_REQUEST_BODY.
    """
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        if required:
            return {}
        return {}
    try:
        import json

        body = json.loads(raw)
    except Exception:
        raise err_bad_body()
    if not isinstance(body, dict):
        raise err_bad_body()
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request("Missing or invalid required string field: %s" % name)
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise err_invalid_request("Invalid string field: %s" % name)
    return v


def req_int(body, name):
    v = body.get(name)
    if not _is_int(v):
        raise err_invalid_request("Missing or invalid required integer field: %s" % name)
    return v


def opt_int(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not _is_int(v):
        raise err_invalid_request("Invalid integer field: %s" % name)
    return v


def req_num(body, name):
    v = body.get(name)
    if not _is_num(v):
        raise err_invalid_request("Missing or invalid required numeric field: %s" % name)
    return v


def opt_num(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not _is_num(v):
        raise err_invalid_request("Invalid numeric field: %s" % name)
    return v


def opt_bool(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, bool):
        raise err_invalid_request("Invalid boolean field: %s" % name)
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request("Missing or invalid enum field: %s" % name)
    return v


def opt_enum(body, name, allowed, default=None):
    v = body.get(name, default)
    if v is not None and (not isinstance(v, str) or v not in allowed):
        raise err_invalid_request("Invalid enum field: %s" % name)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit/offset, defaults 10/0, min 1, max 100
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
            raise err_invalid_request("Invalid limit.")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit out of range [1, 100].")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("Invalid offset.")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0.")
    return limit, offset


def paginate(records, serializer):
    """records: full matching list (already sorted); returns a Flask response."""
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset:offset + limit]
    return envelope_list([serializer(r) for r in page], limit, offset, total)


def sorted_by_created(records):
    return sorted(records, key=lambda r: (r["_created_dt"], r["_seq"]))


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------


def new_id():
    import uuid

    return str(uuid.uuid4())


def stamp_new(entity, with_version=True):
    """Set id/created_at/updated_at/version on a fresh entity dict."""
    entity["id"] = new_id()
    ts = now_dt()
    entity["_created_dt"] = ts
    entity["_seq"] = next(db.seq)
    entity["created_at"] = iso(ts)
    if with_version:
        entity["updated_at"] = iso(ts)
        entity["version"] = 1
    return entity


def bump(entity):
    """PRD 2.4: version increments by exactly 1 on every state transition,
    side-effect write, or PATCH of that entity; updated_at refreshes on every
    mutation. TestPoint and ProgramVersion carry neither field."""
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = now_iso()
