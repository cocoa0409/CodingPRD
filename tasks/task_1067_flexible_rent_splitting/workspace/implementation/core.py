"""Core: in-memory store, logical clock, response envelope, auth, helpers."""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import request, jsonify

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLES = {"PlatformAdmin", "Underwriter", "CollectionsAgent",
         "CollectionsManager", "Renter", "PropertyManager"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store (wiped on every process boot)
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.properties = {}
        self.renters = {}
        self.applications = {}
        self.billing_cycles = {}
        self.installments = {}
        self.remittances = {}
        self.autopay_mandates = {}
        self.delinquency_cases = {}
        self.recovery_actions = {}
        self.reminders = {}
        self.ledger_entries = {}


db = DB()

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_CLOCK_DEFAULT = "2026-07-01T00:00:00Z"
_clock = None  # aware datetime


def _boot_clock():
    global _clock
    _clock = parse_dt(_CLOCK_DEFAULT)


def get_clock():
    return _clock


def set_clock(iso_value):
    global _clock
    _clock = parse_dt(iso_value)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if s is None:
        raise ValueError("null datetime")
    if not isinstance(s, str):
        raise ValueError("datetime must be string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    if len(v) == 10:  # date only
        v = v + "T00:00:00+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


def clock_iso():
    return iso_ms(get_clock())


def days_floor(later_dt, earlier_dt):
    """Whole-day floor of elapsed time between two aware datetimes."""
    delta = later_dt - earlier_dt
    return int(delta.total_seconds() // 86400)


def add_days_iso(anchor_iso, days):
    return iso_ms(parse_dt(anchor_iso) + timedelta(days=int(days)))


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_full():
    now = now_iso()
    return {"id": new_id(), "created_at": now, "updated_at": now,
            "version": 1, "_seq": next_seq()}


def base_append():
    return {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    pag = {"limit": limit, "offset": offset, "total_count": total,
           "has_more": (offset + len(items)) < total}
    body = {"meta": _meta(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


def err_response(e: ApiError):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def auth(*allowed_roles):
    """Decorator: enforce authentication + role membership for the endpoint."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not uid.strip() or not role or not role.strip():
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "Missing authentication headers.")
            if role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED", 403,
                               "Role not permitted for this operation.")
            return fn(*a, **kw)
        return wrapper
    return deco


def caller():
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object.")
    return b


def require_fields(b, *names):
    for n in names:
        if n not in b or b[n] is None:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % n)


def as_int(b, name, required=True, minimum=None, maximum=None, non_negative=False,
           positive=False):
    if name not in b or b[name] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "%s must be an integer." % name)
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", 400, "%s must be > 0." % name)
    if non_negative and v < 0:
        raise ApiError("ERR_VALIDATION", 400, "%s must be >= 0." % name)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, "%s below minimum." % name)
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", 400, "%s above maximum." % name)
    return v


def as_str(b, name, required=True):
    if name not in b or b[name] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    v = b[name]
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_VALIDATION", 400, "%s must be a non-empty string." % name)
    return v


def as_enum(b, name, allowed, required=True):
    if name not in b or b[name] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, "Missing required field: %s" % name)
        return None
    v = b[name]
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "%s has an invalid value." % name)
    return v


def paginate(items):
    """items is an already-sorted list; apply limit/offset query params."""
    q = request.args
    try:
        limit = int(q.get("limit", 10))
        offset = int(q.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "limit/offset must be integers.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_seq(items):
    return sorted(items, key=lambda r: r["_seq"])
