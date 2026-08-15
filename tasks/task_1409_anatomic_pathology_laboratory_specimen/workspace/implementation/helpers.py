"""Wire helpers: response envelope, auth headers, body shape validation,
time formatting/parsing, Decimal rounding, pagination."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

from db import db
from errors import ApiError

ROLES = {"LabAdmin", "Histotech", "PathologyAssistant", "Pathologist"}

# ---------------------------------------------------------------------------
# logical clock / time formatting
# ---------------------------------------------------------------------------

def now():
    """Current logical clock value (never wall time)."""
    return db.clock


def ts(dt):
    """Second-precision UTC ISO 8601, e.g. 2026-08-09T16:00:00Z.
    Used for computed datetimes and system event timestamps."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts3(dt):
    """Millisecond-precision UTC ISO 8601, e.g. 2026-08-01T00:00:00.000Z.
    Used for created_at / updated_at / api_request_timestamp (PRD section 2)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns tz-aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date_str(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False

# ---------------------------------------------------------------------------
# Decimal rounding
# ---------------------------------------------------------------------------

def round1(value):
    """round-half-up to 1 decimal place, returns Decimal."""
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

# ---------------------------------------------------------------------------
# response envelope
# ---------------------------------------------------------------------------

def ok(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": ts3(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_response(err):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": ts3(now()),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status

# ---------------------------------------------------------------------------
# auth (priority 1 and 2 role membership)
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, *allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "Role %s is not permitted for this endpoint" % role)


def forbid(msg="Entity-backed ownership check failed"):
    raise ApiError("ERR_FORBIDDEN", 403, msg)

# ---------------------------------------------------------------------------
# body shape validation (priority 3)
# ---------------------------------------------------------------------------

def payload():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def need_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or v == "":
        _bad("Field '%s' is required and must be a non-empty string" % key)
    return v


def opt_str(d, key, default=None):
    v = d.get(key, default)
    if v is not None and not isinstance(v, str):
        _bad("Field '%s' must be a string" % key)
    return v


def need_enum(d, key, allowed):
    v = d.get(key)
    if v not in allowed:
        _bad("Field '%s' must be one of %s" % (key, sorted(allowed)))
    return v


def opt_enum(d, key, allowed, default=None):
    v = d.get(key, default)
    if v not in allowed:
        _bad("Field '%s' must be one of %s" % (key, sorted(allowed)))
    return v


def need_int(d, key):
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field '%s' is required and must be an integer" % key)
    return v


def need_num(d, key):
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field '%s' is required and must be a number" % key)
    return Decimal(str(v))


def need_bool(d, key):
    v = d.get(key)
    if not isinstance(v, bool):
        _bad("Field '%s' is required and must be a boolean" % key)
    return v


def opt_bool(d, key, default=None):
    v = d.get(key, default)
    if v is not None and not isinstance(v, bool):
        _bad("Field '%s' must be a boolean" % key)
    return v


def need_dt(d, key):
    v = d.get(key)
    p = parse_dt(v)
    if p is None:
        _bad("Field '%s' is required and must be an ISO 8601 datetime" % key)
    return p


def occ_int(d, key):
    """OCC expected-version field: accept int or digit string."""
    v = d.get(key)
    if isinstance(v, bool):
        _bad("Field '%s' is required and must be an integer" % key)
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.isdigit():
        return int(v)
    _bad("Field '%s' is required and must be an integer" % key)

# ---------------------------------------------------------------------------
# pagination (limit/offset; sorted by created_at ascending)
# ---------------------------------------------------------------------------

def qparam(name):
    """Filter parameter from the query string, falling back to a JSON body
    (some test harnesses send filters as a JSON payload on GET)."""
    v = request.args.get(name)
    if v is not None:
        return v
    if request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict) and name in body:
            v = body[name]
            return None if v is None else str(v)
    return None


def _qint(name, default):
    raw = qparam(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Query parameter '%s' must be an integer" % name)


def paginate(items):
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    limit = _qint("limit", 10)
    offset = _qint("offset", 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
