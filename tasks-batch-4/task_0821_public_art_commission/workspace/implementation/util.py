"""Shared infrastructure: response envelope, errors, auth, time, money."""
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from flask import request, g, jsonify

import db

# ---------------------------------------------------------------------------
# Error catalog (error_id -> http status)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_OWNER": 403,
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_COMMISSION_NOT_FOUND": 404,
    "ERR_CALL_NOT_FOUND": 404,
    "ERR_SUBMISSION_NOT_FOUND": 404,
    "ERR_ARTIST_NOT_FOUND": 404,
    "ERR_PANELIST_NOT_FOUND": 404,
    "ERR_SCORE_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_MILESTONE_NOT_FOUND": 404,
    "ERR_ARTWORK_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_LOAN_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_PANELIST_CONFLICT": 422,
    "ERR_QUORUM_NOT_MET": 409,
    "ERR_DUPLICATE_SCORE": 409,
    "ERR_DUPLICATE_SUBMISSION": 409,
    "ERR_SUBMISSION_CALL_MISMATCH": 422,
    "ERR_DEADLINE_PASSED": 422,
    "ERR_SITE_INTERVAL_CONFLICT": 409,
    "ERR_LOAN_INTERVAL_CONFLICT": 409,
    "ERR_MILESTONE_PCT_SUM": 422,
    "ERR_DONATION_TYPE_REQUIRED": 422,
    "ERR_ALLOCATION_EXCEEDS_BUDGET": 422,
    "ERR_CONTRACT_EXCEEDS_ALLOCATION": 422,
    "ERR_DEACCESSION_BLOCKED_BY_LOAN": 409,
    "ERR_VALIDATION": 422,
}

ROLES = {"ProgramAdmin", "Registrar", "Artist", "Panelist"}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with three fractional digits and Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(db.now_dt())


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime. Raise ApiError on failure."""
    if not isinstance(value, str) or not value:
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------
def round_half_up_cents(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(dec_value):
    return Decimal(dec_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# IDs / request ids
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Record lifecycle
# ---------------------------------------------------------------------------
def new_record(fields, common=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    rec["_seq"] = db.next_seq()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: bump version + updated_at."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count, status=200):
    has_more = offset + len(items) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), status


def ok_array(items, status=200):
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status


def err_response(error_id, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_HTTP.get(error_id, 400)


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = uid
    g.role = role
    return uid, role


def authorize(allowed_roles):
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s not permitted for this operation" % g.role)


def guard(allowed_roles):
    """Authenticate then authorize against the allowed role set."""
    authenticate()
    authorize(allowed_roles)


# ---------------------------------------------------------------------------
# Body parsing / validation helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def require_str(data, key):
    v = data.get(key)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "field '%s' must be a non-empty string" % key)
    return v


def require_int(data, key, minimum=None, maximum=None):
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "field '%s' must be an integer" % key)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", "field '%s' below minimum" % key)
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", "field '%s' above maximum" % key)
    return v


def require_enum(data, key, allowed):
    v = data.get(key)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", "field '%s' must be one of %s" % (key, sorted(allowed)))
    return v


def require_number(data, key):
    v = data.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", "field '%s' must be a number" % key)
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate_params():
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sort_and_page(records, limit, offset):
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
