"""Envelope, errors, auth, validation and pagination primitives.

All structural names (headers, envelope fields, pagination params, role names)
come straight from SCAFFOLD.yaml / PRD.md — nothing is assumed.
"""
import random
import string
import uuid
from datetime import datetime, date, timezone
from functools import wraps

from flask import request, jsonify

from store import db

# Declared roles (PRD section 2.1).
ROLES = ("Registrar", "FinancialCounselor", "FrontDeskAgent", "AccessSupervisor")


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ---------------------------------------------------------------- time helpers
def now():
    """Current logical time. Never falls back to wall-clock."""
    return db.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_iso():
    return iso(datetime.now(timezone.utc))


def parse_dt(v):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "malformed datetime value")
    s = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "malformed datetime value")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_d(s):
    return date.fromisoformat(s)


# ------------------------------------------------------------- envelope helpers
def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta(extra=None):
    m = {"api_request_id": new_request_id(), "api_request_timestamp": wall_iso()}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": data}), status


def ok_list(items, page_meta):
    return jsonify({"meta": meta(page_meta), "response_type": "array", "data": items}), 200


def error_response(e):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.status


# ---------------------------------------------------------------------- records
def new_record():
    ts = iso(now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = iso(now())


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(table, rid, what="resource"):
    rec = getattr(db, table).get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found" % what)
    return rec


# ------------------------------------------------------------------------- auth
def authed(*allowed):
    """Enforce X-User-ID / X-User-Role headers, then endpoint role permission."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED", 401,
                    "missing or invalid X-User-ID / X-User-Role headers",
                )
            if role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN", 403,
                    "role %s is not permitted for this endpoint" % role,
                )
            return fn(*a, **kw)

        return wrapper

    return deco


# --------------------------------------------------------------- body validation
def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return b


def _present(b, name):
    return name in b and b[name] is not None


def v_str(b, name, required=True):
    if not _present(b, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' is required" % name)
        return None
    v = b[name]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be a non-empty string" % name)
    return v


def v_enum(b, name, allowed, required=True):
    v = v_str(b, name, required)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "field '%s' must be one of %s" % (name, sorted(allowed)),
        )
    return v


def v_int(b, name, minv=None, maxv=None, required=True):
    if not _present(b, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' is required" % name)
        return None
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be an integer" % name)
    if minv is not None and v < minv:
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be >= %d" % (name, minv))
    if maxv is not None and v > maxv:
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be <= %d" % (name, maxv))
    return v


def v_bool(b, name, required=True):
    if not _present(b, name):
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' is required" % name)
        return None
    v = b[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field '%s' must be a boolean" % name)
    return v


def v_date(b, name, required=True):
    v = v_str(b, name, required)
    if v is None:
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "field '%s' must be an ISO date (YYYY-MM-DD)" % name,
        )
    return v


def v_datetime(b, name, required=True):
    v = v_str(b, name, required)
    if v is None:
        return None
    return parse_dt(v)


# ------------------------------------------------------------------ pagination
def _qint(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "%s must be an integer" % name)


def pagination_params():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _qint(raw_limit, "limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        offset = _qint(raw_offset, "offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items):
    """Sort by created_at ascending (insertion order breaks ties), then paginate."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    limit, offset = pagination_params()
    page = ordered[offset:offset + limit]
    page_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [serialize(r) for r in page], page_meta
