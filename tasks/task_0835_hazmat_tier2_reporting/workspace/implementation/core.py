"""Core infrastructure: in-memory store, logical clock, helpers, errors,
response envelope, auth, pagination, and validation utilities."""

import random
import string
import uuid
from datetime import datetime, timezone, timedelta

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Constants (from SCAFFOLD calculation tables)
# ---------------------------------------------------------------------------
NON_EHS_THRESHOLD_LBS = 10000
EHS_TPQ_CAP_LBS = 500

BASE_FEE_CENTS = 5000
PROVISIONAL_RATE_CENTS = 2000
INCLUDED_CHEMICALS = 5
TIER1_MAX = 25
TIER1_RATE_CENTS = 2000
TIER2_RATE_CENTS = 1000
EHS_SURCHARGE_CENTS = 5000
# late penalty pct handled with Decimal in logic

RMP_RESUBMIT_YEARS = 5
RMP_DUE_WINDOW_DAYS = 90
MIN_INSPECTION_GAP_HOURS = 24
LBS_PER_UNIT = 1000

ROLES = {"Regulator", "FacilityOperator", "LEPCCoordinator"}

CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store (empty on every process boot — never seeded)
# ---------------------------------------------------------------------------
facilities = {}
chemicals = {}
inventories = {}
filings = {}
sds_docs = {}
releases = {}
lepc_notices = {}
permits = {}
inspections = {}
cases = {}
rmps = {}

_clock = {"now": CLOCK_DEFAULT}
_seq = {"n": 0}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def format_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def parse_dt(s):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("empty datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # date-only fallback
        dt = datetime.strptime(txt, "%Y-%m-%d")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, n):
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:
        # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + n, day=28)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": format_dt(now()),
    }
    if pagination:
        m.update(pagination)
    return m


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def ok_array(items, limit, offset, total, code=200):
    pg = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    body = {"meta": _meta(pg), "response_type": "array", "data": items}
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADER", 400, "Missing or unrecognized authentication headers")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def require_owner(role, uid, facility_id):
    if role == "FacilityOperator" and uid != facility_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "FacilityOperator may only act on its own facility")


# ---------------------------------------------------------------------------
# Body / pagination / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def bad(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def require_present(body, field):
    if field not in body or body[field] is None:
        raise bad(f"Missing required field: {field}")
    return body[field]


def as_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str) or v == "":
        raise bad(f"Field {field} must be a non-empty string")
    return v


def as_enum(body, field, allowed):
    v = require_present(body, field)
    if v not in allowed:
        raise bad(f"Field {field} must be one of {sorted(allowed)}")
    return v


def as_int(body, field, non_negative=True):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad(f"Field {field} must be an integer")
    if non_negative and v < 0:
        raise bad(f"Field {field} must be non-negative")
    return v


def as_number(body, field, non_negative=True):
    v = require_present(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad(f"Field {field} must be a number")
    if non_negative and v < 0:
        raise bad(f"Field {field} must be non-negative")
    return v


def as_bool(body, field):
    v = require_present(body, field)
    if not isinstance(v, bool):
        raise bad(f"Field {field} must be a boolean")
    return v


def as_dt(body, field):
    v = require_present(body, field)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise bad(f"Field {field} must be an ISO-8601 datetime")


def paginate(items):
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    try:
        limit = 10 if limit is None else int(limit)
        offset = 0 if offset is None else int(offset)
    except (ValueError, TypeError):
        raise bad("Pagination parameters must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def touch(entity):
    """Record a mutation: bump updated_at (logical clock) and version."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1


def base_record():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
