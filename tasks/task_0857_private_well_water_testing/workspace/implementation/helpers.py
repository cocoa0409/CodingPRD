"""Shared helpers: errors, response envelope, datetime, auth, validation."""
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

from store import store

# ---------------------------------------------------------------------------
# Error catalogue (PRD §5 / scaffold 1.6)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 400,
    "ERR_ANALYTE_OUT_OF_RANGE": 400,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_DRILLER_NOT_FOUND": 404,
    "ERR_AQUIFER_NOT_FOUND": 404,
    "ERR_WELL_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_DRILLER_LOG_NOT_FOUND": 404,
    "ERR_SAMPLE_NOT_FOUND": 404,
    "ERR_RESULT_NOT_FOUND": 404,
    "ERR_ADVISORY_NOT_FOUND": 404,
    "ERR_CASE_NOT_FOUND": 404,
    "ERR_ABANDONMENT_NOT_FOUND": 404,
    "ERR_REQUIREMENT_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_PERMIT_NOT_ISSUED": 409,
    "ERR_REQUIREMENT_NOT_OPEN": 409,
    "ERR_WELL_NOT_ACTIVE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SELF_CLOSE_FORBIDDEN": 403,
    "ERR_SETBACK_VIOLATION": 422,
    "ERR_DRILLER_LICENSE_INVALID": 422,
    "ERR_DRILLER_NOT_ASSIGNED": 409,
    "ERR_APPLICANT_MISMATCH": 409,
    "ERR_SAMPLE_OUTSIDE_VALIDITY_WINDOW": 422,
    "ERR_DRILLER_SCHEDULE_CONFLICT": 409,
    "ERR_ADVISORY_WINDOW_OVERLAP": 409,
    "ERR_SAMPLE_NOT_SAFE": 422,
    "ERR_ABANDONMENT_BLOCKED": 409,
    "ERR_FEE_UNPAID": 402,
}

ROLES = {"Applicant", "Driller", "LabAnalyst", "HealthOfficer"}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# datetime rendering / parsing — ONE renderer for every datetime in the system
# ---------------------------------------------------------------------------
def render_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant to an aware UTC datetime, or raise ApiError."""
    if not isinstance(value, str):
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


def round_half_up(value, places=0):
    """Decimal round-half-away-from-zero to the given decimal places."""
    q = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_dt(store.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1) — authentication then authorization
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return Ctx(user_id, role)


def authorize(ctx, allowed_roles):
    if ctx.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s is not permitted for this endpoint" % ctx.role)


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        raw = request.get_data(cache=True)
        if not raw:
            return {}
        data = request.get_json(silent=True)
        if data is None or not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
        return data
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", "Field %s must be a non-empty string" % field)
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def require_int(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", "Field %s must be an integer" % field)
    return v


def require_number(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", "Field %s must be a number" % field)
    return v


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", "Field %s must be a boolean" % field)
    return v


# ---------------------------------------------------------------------------
# Pagination + listing (PRD §2.3)
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows, serialize):
    """rows: list of entity dicts already filtered. Sort, page, envelope."""
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = get_pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success([serialize(r) for r in page], status=200,
                   response_type="array", pagination=pagination)


def filter_rows(collection, filters):
    """filters: dict of field -> query-param-name. Returns matching rows."""
    args = request.args
    rows = list(collection.values())
    for field, param in filters.items():
        if param in args and args.get(param) != "":
            val = args.get(param)
            rows = [r for r in rows if str(r.get(field)) == val]
    return rows
