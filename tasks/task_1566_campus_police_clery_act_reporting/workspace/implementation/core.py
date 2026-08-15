"""Shared infrastructure: store, clock, errors, envelope, auth, validation."""

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

UTC = timezone.utc

# ----------------------------------------------------------------- errors ---

class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


# ------------------------------------------------------------------ clock ---

class _Clock:
    """Server-side logical clock; never falls back to wall-clock time."""

    def __init__(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


clock = _Clock()

# ------------------------------------------------------------------ store ---

class _DB:
    def __init__(self):
        self.geographies = {}
        self.csas = {}
        self.training_records = {}
        self.referrals = {}
        self.incidents = {}
        self.offense_counts = {}
        self.alerts = {}
        self.log_entries = {}
        self.inspection_requests = {}
        self.asrs = {}
        self.statistic_lines = {}
        self.fire_incidents = {}
        self.fire_safety_reports = {}
        self.program_reviews = {}
        self.corrective_actions = {}
        self.entity_seq = 0
        self.incident_seq = 0
        self.log_entry_seq = 0


db = _DB()

# -------------------------------------------------------------- date/time ---

def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, "Expected an ISO-8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "Malformed datetime: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date(value):
    if not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, "Expected an ISO date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, "Malformed date: %r" % value)


def fmt_dt(dt):
    """Canonical PRD wire format for created_at / updated_at / request timestamp:
    always three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt_short(dt):
    """ISO 8601 UTC format used for domain timestamps (forwarded_at, closed_at,
    due_at, etc.). Whole-second values render without fractional digits (matching
    PRD §2.4's literal style); sub-second values carry three fractional digits."""
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(clock.current)


def now_iso_short():
    return fmt_dt_short(clock.current)


def business_days_between(t0, t1):
    """Dates strictly after date(t0) up to and including date(t1) that are Mon-Fri."""
    d0, d1 = t0.date(), t1.date()
    n = 0
    d = d0 + timedelta(days=1)
    while d <= d1:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def add_business_days(dt, n):
    cur = dt.date()
    added = 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return datetime(cur.year, cur.month, cur.day, dt.hour, dt.minute, dt.second,
                    dt.microsecond, tzinfo=UTC)


def round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def json_number(x):
    """Normalize a summed Decimal/float for JSON output."""
    d = Decimal(str(x))
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# --------------------------------------------------------------- envelope ---

def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    return meta


def success(data, status=200, pagination=None):
    response_type = "array" if isinstance(data, list) else "object"
    return jsonify({"meta": make_meta(pagination),
                    "response_type": response_type,
                    "data": data}), status


def error_response(e):
    return jsonify({"meta": make_meta(),
                    "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.status


# --------------------------------------------------------------- entities ---

def mint(fields=None):
    db.entity_seq += 1
    e = {"id": str(uuid.uuid4()),
         "created_at": now_iso(),
         "updated_at": now_iso(),
         "version": 1,
         "_seq": db.entity_seq}
    if fields:
        e.update(fields)
    return e


def touch(e):
    e["updated_at"] = now_iso()
    e["version"] += 1


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def sort_items(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def get_or_404(store, entity_id):
    e = store.get(entity_id)
    if e is None:
        err("ERR_NOT_FOUND", 404, "Resource not found: %s" % entity_id)
    return e


# ------------------------------------------------------------------- auth ---

ROLES = {"SystemAdmin", "CleryCoordinator", "PoliceChief",
         "CampusSecurityAuthority", "FederalReviewer", "Anonymous"}


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                err("ERR_UNAUTHENTICATED", 401,
                    "Missing or unrecognized X-User-ID / X-User-Role headers")
            if role not in roles:
                err("ERR_FORBIDDEN", 403, "Role %s not permitted on this endpoint" % role)
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return inner
    return deco


# ------------------------------------------------------------ body fields ---

_MISSING = object()


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _fetch(data, name, required):
    v = data.get(name, _MISSING)
    if v is _MISSING:
        if required:
            err("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
        return _MISSING
    return v


def req_str(data, name):
    v = _fetch(data, name, True)
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % name)
    return v


def opt_str(data, name, default=None):
    v = _fetch(data, name, False)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a string" % name)
    return v


def req_int(data, name):
    v = _fetch(data, name, True)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    return v


def opt_int(data, name, default=None):
    v = _fetch(data, name, False)
    if v is _MISSING or v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    return v


def req_number(data, name):
    v = _fetch(data, name, True)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a number" % name)
    return v


def opt_bool(data, name, default=None):
    v = _fetch(data, name, False)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % name)
    return v


def req_dt(data, name):
    """Returns (raw_string, parsed_datetime)."""
    v = _fetch(data, name, True)
    return v, parse_dt(v)


def opt_dt(data, name):
    v = _fetch(data, name, False)
    if v is _MISSING or v is None:
        return None, None
    return v, parse_dt(v)


def req_list(data, name):
    v = _fetch(data, name, True)
    if not isinstance(v, list):
        err("ERR_INVALID_REQUEST", 400, "Field %s must be an array" % name)
    return v


def enum_or_422(value, allowed, field):
    if value not in allowed:
        err("ERR_VALIDATION_FAILED", 422,
            "Invalid value for %s: %r" % (field, value))
    return value


# ------------------------------------------------------------ pagination ----

def paginate(items):
    items = sort_items(items)
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION_FAILED", 422, "Invalid limit parameter")
        if limit < 1 or limit > 100:
            err("ERR_VALIDATION_FAILED", 422, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION_FAILED", 422, "Invalid offset parameter")
        if offset < 0:
            err("ERR_VALIDATION_FAILED", 422, "offset must be >= 0")
    total = len(items)
    window = items[offset:offset + limit]
    page = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + len(window) < total}
    return window, page


# ------------------------------------------------- lazy clock transitions ---

def refresh_csa(csa):
    """Lazy evaluation: ACTIVE -> LAPSED once the clock passes expiry."""
    if csa["status"] == "ACTIVE":
        exp = csa.get("_cert_expires_dt")
        if exp is not None and clock.current > exp:
            csa["status"] = "LAPSED"
            touch(csa)
            rid = csa.get("active_training_record_id")
            rec = db.training_records.get(rid) if rid else None
            if rec is not None and rec["status"] == "ACTIVE":
                rec["status"] = "EXPIRED"
                touch(rec)


def refresh_training_record(rec):
    if rec["status"] == "ACTIVE" and clock.current > rec["_valid_to_dt"]:
        rec["status"] = "EXPIRED"
        touch(rec)
        csa = db.csas.get(rec["csa_id"])
        if (csa is not None and csa["status"] == "ACTIVE"
                and csa.get("active_training_record_id") == rec["id"]):
            csa["status"] = "LAPSED"
            touch(csa)
