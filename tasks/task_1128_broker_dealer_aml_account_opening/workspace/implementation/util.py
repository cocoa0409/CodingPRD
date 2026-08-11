"""Response envelope, auth context, and request-validation helpers.

Envelope (scaffold §1.0 / PRD §2.2):
  success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
            "response_type": "object"|"array", "data": ...}
  error:   {"meta": {...}, "response_type": "error",
            "data": {"error_id", "message"}}
Pagination params: limit (default 10, min 1, max 100), offset (default 0);
list meta adds limit/offset/total_count/has_more.
Auth headers: X-User-ID + X-User-Role (PRD §2.1).
"""

import json
import re
import uuid
from datetime import datetime, timezone, date
from functools import wraps

from flask import g, jsonify, request

from db import now_iso, serialize, sorted_records
from errors import ApiError

VALID_ROLES = {
    "RegisteredRep",
    "AMLAnalyst",
    "ComplianceOfficer",
    "SAROfficer",
    "OperationsAnalyst",
    "IndependentAuditor",
    "SystemAdmin",
}
ALL_ROLES = sorted(VALID_ROLES)

MISSING = object()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": now_iso(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(records, limit, offset):
    """records: pre-filtered, pre-sorted raw records."""
    total = len(records)
    page = records[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array",
            "data": [serialize(r) for r in page]}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth (validation priorities 1-2)
# ---------------------------------------------------------------------------

def endpoint(allowed_roles):
    """Decorator: validate X-User-ID / X-User-Role, then role permission."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if (uid is None or not isinstance(uid, str) or uid.strip() == ""
                    or role is None or role not in VALID_ROLES):
                raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                               "X-User-ID and X-User-Role headers are required and must be well-formed")
            if role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED_ROLE", 403,
                               "Role %s is not permitted for this endpoint" % role)
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Body / field access (deferred validation: ERR_INVALID_REQUEST is priority 21,
# evaluated only after every business check above has passed)
# ---------------------------------------------------------------------------

def body():
    """Parsed JSON object body; None when malformed/non-object; {} when empty."""
    if hasattr(g, "_body"):
        return g._body
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        g._body = {}
    else:
        try:
            v = json.loads(raw)
        except Exception:
            v = None
        g._body = v if isinstance(v, dict) else None
    return g._body


def field(name):
    b = body()
    if not isinstance(b, dict):
        return MISSING
    return b.get(name, MISSING)


def is_str(v):
    return isinstance(v, str)


def is_nonempty_str(v):
    return isinstance(v, str) and v.strip() != ""


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_bool(v):
    return isinstance(v, bool)


def is_list(v):
    return isinstance(v, list)


def parse_date(s):
    """Strict YYYY-MM-DD -> date, else None."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def require_fields(spec):
    """Final body-shape gate (priority 21) -> ERR_INVALID_REQUEST.

    spec: list of (name, kind) where kind is 'str'|'nstr'|'num'|'int'|'bool'|
    'list'|'date'. Only fields present are checked here for type; required
    fields must additionally be present.
    """
    b = body()
    if b is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    for name, kind, required in spec:
        v = b.get(name, MISSING)
        if v is MISSING:
            if required:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "Missing required field: %s" % name)
            continue
        if not _kind_ok(v, kind):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Field %s has an invalid value or type" % name)


def _kind_ok(v, kind):
    if kind == "str":
        return is_str(v)
    if kind == "nstr":
        return is_nonempty_str(v)
    if kind == "num":
        return is_num(v)
    if kind == "int":
        return is_int(v)
    if kind == "bool":
        return is_bool(v)
    if kind == "list":
        return is_list(v)
    if kind == "date":
        return parse_date(v) is not None
    return True


def check_enum(name, allowed):
    """Enum gate (priority 15) -> ERR_INVALID_ENUM when present and invalid."""
    v = field(name)
    if v is MISSING:
        return None
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_INVALID_ENUM", 400,
                       "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def list_response(records, filters, enum_filters=()):
    """filters: {field: raw query value or None}; enum_filters validated first."""
    for fname, allowed in enum_filters:
        v = request.args.get(fname)
        if v is not None and v not in allowed:
            raise ApiError("ERR_INVALID_ENUM", 400,
                           "Query parameter %s must be one of %s" % (fname, sorted(allowed)))
    limit, offset = pagination()
    out = [r for r in records
           if all(v is None or r.get(k) == v for k, v in filters.items())]
    return ok_list(sorted_records(out), limit, offset)


def parse_bool_param(name):
    v = request.args.get(name)
    if v is None:
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    raise ApiError("ERR_INVALID_REQUEST", 400,
                   "Query parameter %s must be true or false" % name)


# ---------------------------------------------------------------------------
# Existence helpers (priority 4, left-to-right)
# ---------------------------------------------------------------------------

def get_or_404(table, rid, error_id):
    from db import store
    rec = getattr(store, table).get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "%s does not exist" % rid)
    return rec


# ---------------------------------------------------------------------------
# ISO datetime parsing for the clock endpoint
# ---------------------------------------------------------------------------

def parse_iso_datetime(s):
    if not isinstance(s, str) or s.strip() == "":
        return None
    txt = s.strip()
    d = parse_date(txt)
    if d is not None:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
