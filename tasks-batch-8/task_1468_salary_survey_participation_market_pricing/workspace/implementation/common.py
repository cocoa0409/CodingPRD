"""Shared foundation: in-memory store, logical clock, errors, envelope, auth, validators."""
import functools
import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone

from flask import g, jsonify, request

ALL_ROLES = ("CompAnalyst", "CompManager", "HRDirector", "CompCommitteeReviewer", "VendorAdmin")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, status, message):
    return ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# In-memory store (starts empty on every boot; no seeding)
# ---------------------------------------------------------------------------
db = {
    "orgs": {},
    "strategies": {},
    "employees": {},
    "jobs": {},
    "vendors": {},
    "surveys": {},
    "benchmarks": {},
    "submissions": {},
    "matches": {},
    "composites": {},
    "cycles": {},
    "adjustments": {},
    "reports": {},
    "audit_events": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


# ---------------------------------------------------------------------------
# Logical clock — starts at exactly 2026-08-01T00:00:00Z; never falls back
# to wall-clock time.
# ---------------------------------------------------------------------------
_clock = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]


def now():
    return _clock[0]


def set_clock(dt):
    _clock[0] = dt


def current_date():
    return now().date()


def iso(dt=None):
    dt = dt if dt is not None else now()
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(s):
    if not isinstance(s, str):
        return None
    ss = s.strip()
    if ss.endswith("Z"):
        ss = ss[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ss)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    """Return a date for a strict YYYY-MM-DD string, else None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record():
    ts = iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["updated_at"] = iso()
    rec["version"] += 1


def pub(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Resource {rid} not found")
    return rec


# ---------------------------------------------------------------------------
# Response envelope (per PRD §2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": iso(),
    }


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(records):
    args = request.args
    raw_limit = args.get("limit", "10")
    raw_offset = args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit and offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    m = _meta()
    m.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    return jsonify({"meta": m, "response_type": "array", "data": [pub(r) for r in page]}), 200


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1)
# ---------------------------------------------------------------------------
def require_roles(*roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not isinstance(uid, str) or not uid.strip() or role not in ALL_ROLES:
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID and X-User-Role headers are required and must be well-formed",
                )
            if role not in roles:
                raise ApiError(
                    "ERR_FORBIDDEN_FOR_ROLE", 403,
                    f"Role {role} is not permitted for this endpoint",
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def actor_employee_id():
    """VendorAdmin and the system are opaque: audit actor is null for them."""
    if g.get("user_role") == "VendorAdmin":
        return None
    return g.get("user_id")


# ---------------------------------------------------------------------------
# Audit (PRD §2.10)
# ---------------------------------------------------------------------------
def emit_audit(org_id, actor_id, action, target_entity, target_id, payload):
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    rec = {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "actor_employee_id": actor_id,
        "action": action,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload_hash": hashlib.sha256(canon.encode("utf-8")).hexdigest(),
        "created_at": iso(),
        "_seq": next_seq(),
    }
    db["audit_events"][rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Request body + field validators (validation ladder rung 4)
# ---------------------------------------------------------------------------
def body():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def v_str(b, k, required=True):
    val = b.get(k)
    if val is None:
        if required:
            _bad(f"Missing required field: {k}")
        return None
    if not isinstance(val, str) or not val.strip():
        _bad(f"Field {k} must be a non-empty string")
    return val


def v_int(b, k, required=True, choices=None, min_v=None, max_v=None):
    val = b.get(k)
    if val is None:
        if required:
            _bad(f"Missing required field: {k}")
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        _bad(f"Field {k} must be an integer")
    if choices is not None and val not in choices:
        _bad(f"Field {k} must be one of {sorted(choices)}")
    if min_v is not None and val < min_v:
        _bad(f"Field {k} must be >= {min_v}")
    if max_v is not None and val > max_v:
        _bad(f"Field {k} must be <= {max_v}")
    return val


def v_enum(b, k, values, required=True):
    val = b.get(k)
    if val is None:
        if required:
            _bad(f"Missing required field: {k}")
        return None
    if val not in values:
        _bad(f"Field {k} must be one of {sorted(values)}")
    return val


def v_date(b, k, required=True):
    val = b.get(k)
    if val is None:
        if required:
            _bad(f"Missing required field: {k}")
        return None
    if parse_date(val) is None:
        _bad(f"Field {k} must be a valid ISO date (YYYY-MM-DD)")
    return val


# ---------------------------------------------------------------------------
# List filtering helper
# ---------------------------------------------------------------------------
def filter_records(collection, filters):
    items = list(db[collection].values())
    for k, v in filters.items():
        if v is not None:
            items = [r for r in items if str(r.get(k)) == v]
    return items
