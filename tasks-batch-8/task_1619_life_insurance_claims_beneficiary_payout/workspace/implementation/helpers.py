"""Foundation helpers: errors, response envelope, auth, dates, money, pagination."""

import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from store import db

# ---------------------------------------------------------------------------
# Error catalog (error_id -> http status), per PRD §5 / SCAFFOLD errors table
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 400,
    "ERR_INSUFFICIENT_PERMISSIONS": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    "ERR_DOCUMENT_NOT_FOUND": 404,
    "ERR_DESIGNATION_NOT_FOUND": 404,
    "ERR_BENEFICIARY_CLAIM_NOT_FOUND": 404,
    "ERR_ELECTION_NOT_FOUND": 404,
    "ERR_ACCOUNT_NOT_FOUND": 404,
    "ERR_MATCH_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_STALE_CLAIM_VERSION": 412,
    "ERR_STALE_POLICY_VERSION": 412,
    "ERR_POLICY_NOT_ACTIVE": 409,
    "ERR_CLAIM_NOT_REVIEWABLE": 409,
    "ERR_CLAIM_NOT_UNDER_REVIEW": 409,
    "ERR_CLAIM_NOT_IN_CONTESTABILITY_REVIEW": 409,
    "ERR_CLAIM_IN_LEGAL_HOLD": 409,
    "ERR_CLAIM_NOT_IN_LEGAL_HOLD": 409,
    "ERR_CLAIM_NOT_APPROVED": 409,
    "ERR_CLAIM_NOT_FILEABLE": 409,
    "ERR_DOCUMENT_ALREADY_REVIEWED": 409,
    "ERR_BENEFICIARY_CLAIM_INVALID_STATE": 409,
    "ERR_BENEFICIARY_CLAIM_NOT_PAYABLE": 409,
    "ERR_ELECTION_NOT_CONFIRMABLE": 409,
    "ERR_ACCOUNT_NOT_WITHDRAWABLE": 409,
    "ERR_CASE_NOT_ACTIONABLE": 409,
    "ERR_MATCH_NOT_PENDING_REVIEW": 409,
    "ERR_DESIGNATION_ALREADY_REVOKED": 409,
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": 403,
    "ERR_REQUIRED_DOCS_INCOMPLETE": 409,
    "ERR_INVALID_DEATH_DATE": 422,
    "ERR_ELECTION_WINDOW_CLOSED": 409,
    "ERR_ESCHEATMENT_NOT_DUE": 409,
    "ERR_DESIGNATION_FROZEN_AFTER_CLAIM": 409,
    "ERR_DESIGNATION_WINDOW_OVERLAP": 409,
    "ERR_SHARE_TOTAL_EXCEEDED": 422,
    "ERR_DESIGNATION_ALREADY_CLAIMED": 409,
    "ERR_ALLOCATION_CAPACITY_EXCEEDED": 409,
    "ERR_STATUTE_ALREADY_EXISTS": 409,
    "ERR_STATUTE_NOT_CONFIGURED": 422,
    "ERR_DESIGNATION_POLICY_MISMATCH": 422,
    "ERR_DESIGNATION_NOT_ACTIVE_AT_DEATH": 422,
    "ERR_BELOW_RAA_MINIMUM": 422,
    "ERR_INSUFFICIENT_ACCOUNT_BALANCE": 422,
    "ERR_NO_PAYABLE_BENEFICIARIES": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        self.error_id = error_id
        self.status = ERROR_STATUS[error_id]
        self.message = message or error_id
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------

def fmt_dt3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Logical-clock stamp format (matches the PRD's startup default rendering)."""
    if dt.microsecond:
        return fmt_dt3(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_dt3(db.now),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(page, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validation priorities 1-2)
# ---------------------------------------------------------------------------

ALL_ROLES = {
    "ClaimsExaminer",
    "ClaimsApprover",
    "PolicyAdministrator",
    "LegalCounsel",
    "ComplianceOfficer",
    "SystemAdmin",
}


def auth(*allowed_roles):
    """Validate identity headers, then role permission. Returns X-User-ID."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        fail(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be recognized",
        )
    if allowed_roles and role not in allowed_roles:
        fail("ERR_INSUFFICIENT_PERMISSIONS", "Role %s is not permitted for this endpoint" % role)
    return uid


# ---------------------------------------------------------------------------
# Request body / field validation (validation priority 3)
# ---------------------------------------------------------------------------

def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _invalid(msg):
    fail("ERR_INVALID_REQUEST", msg)


def req_string(data, name):
    v = data.get(name)
    if v is None or not isinstance(v, str) or v == "":
        _invalid("%s is required and must be a non-empty string" % name)
    return v


def opt_string(data, name):
    v = data.get(name)
    if v is not None and not isinstance(v, str):
        _invalid("%s must be a string" % name)
    return v


def req_enum(data, name, domain):
    v = data.get(name)
    if v not in domain:
        _invalid("%s must be one of %s" % (name, sorted(domain)))
    return v


def req_int(data, name, positive=False):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("%s is required and must be an integer" % name)
    if positive and v <= 0:
        _invalid("%s must be greater than zero" % name)
    return v


def opt_int(data, name):
    v = data.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("%s must be an integer" % name)
    return v


def req_date(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        _invalid("%s is required and must be an ISO date (YYYY-MM-DD)" % name)
    return parse_date(v, name)


def parse_date(s, name="date"):
    if not isinstance(s, str):
        _invalid("%s must be an ISO date (YYYY-MM-DD)" % name)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        _invalid("%s must be an ISO date (YYYY-MM-DD)" % name)


def parse_datetime_iso(s, name="to_iso8601"):
    if not isinstance(s, str):
        _invalid("%s must be an ISO 8601 timestamp" % name)
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        _invalid("%s must be an ISO 8601 timestamp" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_share_percent(data, name="share_percent"):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid("%s is required and must be a number" % name)
    d = Decimal(str(v))
    if d <= 0 or d > 100:
        _invalid("%s must be greater than 0 and at most 100" % name)
    if -d.as_tuple().exponent > 2:
        _invalid("%s must carry at most two decimal places" % name)
    return v


# ---------------------------------------------------------------------------
# Date arithmetic (calendar months/years with day-of-month clamping)
# ---------------------------------------------------------------------------

def add_months(d, months):
    total = (d.year * 12 + (d.month - 1)) + months
    y, m0 = divmod(total, 12)
    mo = m0 + 1
    day = min(d.day, calendar.monthrange(y, mo)[1])
    return date(y, mo, day)


def add_years(d, years):
    return add_months(d, years * 12)


def complete_months_between(start, end):
    """Complete calendar months from start to end; a month completes on the
    same day-of-month as the start (clamped to month end)."""
    if end < start:
        return 0
    m = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, m) > end:
        m -= 1
    return max(0, m)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal to integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    """Sort by created_at ASC and apply limit/offset. Returns (page, total, limit, offset).
    The sort is stable, so resources sharing a logical-clock creation timestamp
    keep their insertion (true creation) order."""
    items = sorted(items, key=lambda r: r["created_at"])
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    return items[offset : offset + limit], total, limit, offset


def list_response(items, serializer):
    page, total, limit, offset = paginate(items)
    return ok_list([serializer(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------

def new_record():
    now = db.now
    return {"id": str(uuid.uuid4()), "created_at": now, "updated_at": now, "version": 1}


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    rec["updated_at"] = db.now
    rec["version"] += 1
