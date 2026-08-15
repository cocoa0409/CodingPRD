"""Core primitives: error type + catalog, response envelope, auth header
extraction, body/field validation, datetime parsing/formatting, and pinned
round-half-up money arithmetic. All structural names (headers, envelope fields,
pagination params, error ids) come straight from SCAFFOLD.yaml / PRD.md."""

import calendar
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import db

UTC = timezone.utc

ROLES = {"PlatformAdmin", "Creator", "Moderator", "Sponsor", "TrustAgent", "AppealsOfficer"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or empty X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_invalid_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_unauthorized(msg="Role not permitted on this endpoint or for this action"):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_ownership(msg="Caller does not own the referenced channel"):
    return ApiError("ERR_CHANNEL_OWNERSHIP_MISMATCH", 403, msg)


def err_invalid_state(msg="Entity is not in a state admitting this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope, verbatim field names)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": iso(db.now()),
    }


def ok_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def err_resp(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Datetime helpers — ISO 8601 UTC rendered with three fractional digits
# ---------------------------------------------------------------------------
def parse_dt(value, field="datetime"):
    if not isinstance(value, str) or not value.strip():
        raise err_invalid_request("Field '%s' must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise err_invalid_request("Field '%s' is not a parseable ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def month_label(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def add_months(dt, n=1):
    """Calendar-month arithmetic: same day-of-month, clamped to month length."""
    total = (dt.month - 1) + n
    y = dt.year + total // 12
    m = total % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Money: integer cents, round half up (ties away from zero), per-event then sum
# ---------------------------------------------------------------------------
def rhu(numer, denom=10000):
    """round_half_up(numer / denom) to integer cents; ties away from zero."""
    q = (Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------------------------------------------------------------------
# Auth (priority 1) + role gating (priority 3)
# ---------------------------------------------------------------------------
def auth():
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role:
        raise err_unauthenticated()
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise err_unauthorized()


# ---------------------------------------------------------------------------
# Body parsing + field validators (priority 2: ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err_invalid_request("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or not v.strip():
        raise err_invalid_request("Field '%s' is required and must be a non-empty string" % name)
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str):
        raise err_invalid_request("Field '%s' must be a string" % name)
    return v


def req_int(b, name, lo=None, hi=None):
    v = b.get(name)
    if not _is_int(v):
        raise err_invalid_request("Field '%s' is required and must be an integer" % name)
    _range_check(v, name, lo, hi)
    return v


def opt_int(b, name, default=None, lo=None, hi=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not _is_int(v):
        raise err_invalid_request("Field '%s' must be an integer" % name)
    _range_check(v, name, lo, hi)
    return v


def _range_check(v, name, lo, hi):
    if lo is not None and v < lo:
        raise err_invalid_request("Field '%s' is below its minimum" % name)
    if hi is not None and v > hi:
        raise err_invalid_request("Field '%s' exceeds its maximum" % name)


def opt_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, bool):
        raise err_invalid_request("Field '%s' must be a boolean" % name)
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request(
            "Field '%s' is required and must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(b, name, allowed, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return v


def req_dt(b, name):
    if name not in b or b[name] is None:
        raise err_invalid_request("Field '%s' is required" % name)
    return parse_dt(b[name], name)


def opt_dt(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    return parse_dt(b[name], name)


# ---------------------------------------------------------------------------
# Pagination (limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit.strip())
        except Exception:
            raise err_invalid_request("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset.strip())
        except Exception:
            raise err_invalid_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise err_invalid_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def paginate(records, limit, offset, serializer):
    """Sort by created_at ascending (insertion order breaks ties), then page."""
    ordered = sorted(records, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(e) for e in page], total, limit, offset)
