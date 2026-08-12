"""Core primitives: in-memory store, logical clock, envelope, errors, auth.

Storage is in-memory only (plain dicts). The store starts empty on every boot;
no seeding anywhere. The logical clock starts at 2026-05-01T00:00:00Z and moves
only via POST /_clock/set_current_utc.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

db = {
    "companies": {},
    "jurisdiction_rules": {},
    "projects": {},
    "parties": {},
    "furnishing_spans": {},
    "notices": {},
    "lien_claims": {},
    "waivers": {},
    "payments": {},
    "bonding_requests": {},
    "foreclosure_referrals": {},
    "stop_notices": {},
    "bond_claims": {},
}

# Logical clock — never consult wall-clock time for business logic.
CLOCK = {"current": datetime(2026, 5, 1, tzinfo=timezone.utc)}


def clock_now():
    return CLOCK["current"]


def clock_date():
    return CLOCK["current"].date()


def set_clock(iso_str):
    dt = parse_iso_datetime(iso_str)
    if dt is None:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be a valid ISO8601 UTC timestamp", 400)
    CLOCK["current"] = dt
    return dt


# ---------------------------------------------------------------------------
# Timestamp / date helpers
# ---------------------------------------------------------------------------


def now_ts():
    """ISO 8601 UTC timestamp with three fractional digits (resource timestamps)."""
    return fmt_ts(datetime.now(timezone.utc))


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_datetime(s):
    if not isinstance(s, str):
        return None
    txt = s.strip()
    m = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$",
        txt,
    )
    if not m:
        return None
    try:
        frac = m.group(7) or ""
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        tzs = m.group(8) or "Z"
        if tzs == "Z":
            tz = timezone.utc
        else:
            sign = 1 if tzs[0] == "+" else -1
            tzc = tzs[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(tzc[:2]), minutes=int(tzc[2:])))
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro, tz,
        ).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    """Parse an ISO calendar date string -> datetime.date or None."""
    if not isinstance(s, str) or not _DATE_RE.match(s.strip()):
        return None
    try:
        y, mth, d = s.strip().split("-")
        from datetime import date as _date
        return _date(int(y), int(mth), int(d))
    except (ValueError, OverflowError):
        return None


def fmt_date(d):
    return d.isoformat() if d is not None else None


def add_calendar_days(d, n):
    return d + timedelta(days=n)


def add_business_days(d, n):
    cur = d
    added = 0
    while added < n:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # Mon..Fri
            added += 1
    return cur


def add_days(d, n, basis):
    if basis == "BUSINESS":
        return add_business_days(d, n)
    return add_calendar_days(d, n)


# ---------------------------------------------------------------------------
# Errors & envelope
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_ts(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    })
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def pagination_params():
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "limit must be an integer", 400)
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "offset must be an integer", 400)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be >= 0", 400)
    return limit, offset


def paginate(records):
    """records: full sorted list. Returns flask response."""
    limit, offset = pagination_params()
    records = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(records)
    page = records[offset:offset + limit]
    return ok_list(page, total, limit, offset)


# ---------------------------------------------------------------------------
# Auth & roles
# ---------------------------------------------------------------------------

ROLES = {"PlatformAdmin", "OpsAgent", "CustomerAdmin", "Counsel"}


def current_role():
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header missing or not a declared role", 401)
    return role


def current_user_id():
    return request.headers.get("X-User-ID")


def require_roles(*allowed):
    role = current_role()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not allowed for this endpoint", 403)
    return role


def scope_company(company_id):
    """Company scoping: a CustomerAdmin must stay within their own company."""
    if current_role() == "CustomerAdmin":
        if current_user_id() != company_id:
            raise ApiError("ERR_FORBIDDEN", "CustomerAdmin may only access their own company's resources", 403)


# ---------------------------------------------------------------------------
# Request body validation
# ---------------------------------------------------------------------------


def body_json(required, optional=(), enums=None, int_fields=(), bool_fields=(),
              date_fields=(), number_fields=(), list_fields=()):
    """Validate JSON body: required fields present, no unknown fields, enum/format checks."""
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object", 400)
    allowed = set(required) | set(optional)
    for key in data:
        if key not in allowed:
            raise ApiError("ERR_VALIDATION", f"Unknown field: {key}", 400)
    for key in required:
        if key not in data or data[key] is None:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {key}", 400)
    enums = enums or {}
    for key, vals in enums.items():
        if key in data and data[key] is not None and data[key] not in vals:
            raise ApiError("ERR_VALIDATION", f"Invalid value for {key}", 400)
    for key in int_fields:
        if key in data and data[key] is not None:
            if isinstance(data[key], bool) or not isinstance(data[key], int):
                raise ApiError("ERR_VALIDATION", f"{key} must be an integer", 400)
    for key in bool_fields:
        if key in data and data[key] is not None:
            if not isinstance(data[key], bool):
                raise ApiError("ERR_VALIDATION", f"{key} must be a boolean", 400)
    for key in number_fields:
        if key in data and data[key] is not None:
            if isinstance(data[key], bool) or not isinstance(data[key], (int, float)):
                raise ApiError("ERR_VALIDATION", f"{key} must be a number", 400)
    for key in date_fields:
        if key in data and data[key] is not None:
            if parse_date(data[key]) is None:
                raise ApiError("ERR_VALIDATION", f"{key} must be an ISO date (YYYY-MM-DD)", 400)
    for key in list_fields:
        if key in data and data[key] is not None:
            if not isinstance(data[key], list):
                raise ApiError("ERR_VALIDATION", f"{key} must be an array", 400)
    return data


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------


def new_entity(fields):
    ts = now_ts()
    ent = {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}
    ent.update(fields)
    return ent


def touch(ent):
    ent["updated_at"] = now_ts()
    ent["version"] += 1


def get_or_404(collection, ent_id):
    ent = db[collection].get(ent_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", f"Resource not found: {ent_id}", 404)
    return ent
