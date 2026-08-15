"""Errors, response envelope, auth, payload validation, pagination, time utils."""
import json
import random
import string
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import request, jsonify

from store import STORE, now

ROLES = {
    "ShopAdmin", "Estimator", "ToolingEngineer", "ProjectManager",
    "QualityManager", "FinanceAdmin", "Customer",
}


class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


def raise_err(error_id, status, message=None):
    raise ApiError(error_id, status, message)


def bad_request(msg="Invalid request"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def bad_enum(msg="Enum value not in declared domain"):
    raise ApiError("ERR_INVALID_ENUM_VALUE", 400, msg)


def not_found(resource):
    raise ApiError("ERR_%s_NOT_FOUND" % resource, 404,
                   "%s not found" % resource.replace("_", " ").lower())


# ---------------------------------------------------------------------------
# Time utilities (logical clock; ISO 8601 UTC with three fractional digits;
# datetime comparisons resolve to the second).
# ---------------------------------------------------------------------------

def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime truncated to
    whole seconds. Raises ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    """Assign id/created_at/updated_at/version plus internal creation order."""
    STORE.seq += 1
    ts = now()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = STORE.seq
    return rec


def stamp_new_noversion(rec):
    """Payments and shot reports: id + created_at only (no updated_at/version)."""
    STORE.seq += 1
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["_seq"] = STORE.seq
    return rec


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = now()


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------

def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def ok(data, status=200):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": fmt_dt(now()),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, status=201)


def ok_list(page, page_meta):
    meta = {
        "api_request_id": _req_id(),
        "api_request_timestamp": fmt_dt(now()),
    }
    meta.update(page_meta)
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), 200


def error_response(err_id, status, message):
    body = {
        "meta": {
            "api_request_id": _req_id(),
            "api_request_timestamp": fmt_dt(now()),
        },
        "response_type": "error",
        "data": {"error_id": err_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validation tiers 1-2)
# ---------------------------------------------------------------------------

def authenticate(required_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 401,
                       "X-User-ID and X-User-Role headers are required and the role must be declared")
    if required_roles is not None and role not in required_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Caller role is not permitted for this endpoint")
    return uid, role


def endpoint(roles=None):
    """Decorator: tier-1 header validity then tier-2 role authorization.
    roles=None means Any (every authenticated role)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = authenticate(roles)
            return fn(uid, role, *args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Request-shape validation (tier 3)
# ---------------------------------------------------------------------------

def get_body():
    raw = request.get_data()
    if not raw or not raw.strip():
        return {}
    try:
        body = json.loads(raw)
    except Exception:
        bad_request("Request body is not valid JSON")
    if not isinstance(body, dict):
        bad_request("Request body must be a JSON object")
    return body


def validate_payload(body, spec):
    """spec: list of (name, kind, required, opts?) tuples.
    kinds: str, int, num, bool, datetime, enum, str_list.
    Unknown keys are rejected; missing required keys are rejected."""
    allowed = {f[0] for f in spec}
    for key in body:
        if key not in allowed:
            bad_request("Unknown field: %s" % key)
    out = {}
    for field in spec:
        name, kind, required = field[0], field[1], field[2]
        opts = field[3] if len(field) > 3 else {}
        if name not in body or body[name] is None:
            if required:
                bad_request("Missing required field: %s" % name)
            continue
        v = body[name]
        if kind == "str":
            if not isinstance(v, str):
                bad_request("Field %s must be a string" % name)
            if opts.get("nonempty") and v == "":
                bad_request("Field %s must be non-empty" % name)
        elif kind == "int":
            if isinstance(v, bool) or not isinstance(v, int):
                bad_request("Field %s must be an integer" % name)
            if "min" in opts and v < opts["min"]:
                bad_request("Field %s is below its minimum" % name)
            if "max" in opts and v > opts["max"]:
                bad_request("Field %s exceeds its maximum" % name)
        elif kind == "num":
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                bad_request("Field %s must be a number" % name)
            if "min" in opts and v < opts["min"]:
                bad_request("Field %s is below its minimum" % name)
            if "max" in opts and v > opts["max"]:
                bad_request("Field %s exceeds its maximum" % name)
        elif kind == "bool":
            if not isinstance(v, bool):
                bad_request("Field %s must be a boolean" % name)
        elif kind == "datetime":
            if not isinstance(v, str):
                bad_request("Field %s must be an ISO8601 datetime string" % name)
            try:
                v = parse_dt(v)
            except Exception:
                bad_request("Field %s is not a valid ISO8601 datetime" % name)
        elif kind == "enum":
            if not isinstance(v, str) or v not in opts["values"]:
                bad_enum("Field %s has an out-of-domain value" % name)
        elif kind == "str_list":
            if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
                bad_request("Field %s must be an array of strings" % name)
            if opts.get("nonempty") and len(v) == 0:
                bad_request("Field %s must be a non-empty array" % name)
        else:
            raise AssertionError("unknown kind %s" % kind)
        out[name] = v
    return out


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0.
# ---------------------------------------------------------------------------

def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def filter_eq(items, field, raw_value):
    if raw_value is None:
        return items
    return [it for it in items if it.get(field) == raw_value]


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
