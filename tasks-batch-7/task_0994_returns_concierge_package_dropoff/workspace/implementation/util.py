"""Cross-cutting helpers: auth headers, response envelope, pagination,
body/field validation, datetime parsing. All structural names come from
SCAFFOLD.yaml response_envelope and PRD section 2."""

import uuid
from datetime import datetime, timezone

from flask import request, jsonify

import db
from errors import ApiError, bad_request, enum_invalid

ROLES = (
    "Shopper", "MerchantAdmin", "LocationOperator",
    "SupportAgent", "CarrierDispatcher", "PlatformAdmin",
)


# ---------------------------------------------------------------- auth ------
def auth():
    """Priority 1: headers present and role declared -> else ERR_UNAUTHENTICATED."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing/invalid X-User-Role or X-User-ID")
    return uid, role


def require_roles(*roles):
    """Priority 2: caller role must be listed for the endpoint."""
    uid, role = auth()
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role not allowed on this endpoint")
    return uid, role


def check(cond, error_id, status, message):
    if not cond:
        raise ApiError(error_id, status, message)


# ------------------------------------------------------------ envelope ------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.fmt_ms(db.now()),
    }


def respond(data, status=200, page=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if page is not None else "object",
        "data": data,
    }
    if page is not None:
        body["meta"].update(page)
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------- pagination ------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def paginate(records):
    """records: full filtered list; sorts created_at ASC (seq tie-break),
    slices per limit/offset, returns (page, page_meta)."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


# --------------------------------------------------------- body / fields ----
def body(required=False):
    b = request.get_json(silent=True)
    if b is None:
        if required:
            bad_request("Request body must be a JSON object")
        return {}
    if not isinstance(b, dict):
        bad_request("Request body must be a JSON object")
    return b


def req_field(b, name):
    if name not in b or b[name] is None:
        bad_request("Missing required field: %s" % name)
    return b[name]


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str) or not v:
        bad_request("Field %s must be a non-empty string" % name)
    return v


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, minimum=None):
    v = req_field(b, name)
    if not is_int(v):
        bad_request("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        bad_request("Field %s must be >= %d" % (name, minimum))
    return v


def req_bool(b, name):
    v = req_field(b, name)
    if not isinstance(v, bool):
        bad_request("Field %s must be a boolean" % name)
    return v


def opt_bool(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], bool):
        bad_request("Field %s must be a boolean" % name)
    return b[name]


def req_enum(b, name, members):
    v = req_field(b, name)
    if not isinstance(v, str) or v not in members:
        enum_invalid("Field %s must be one of %s" % (name, ", ".join(members)))
    return v


def req_number(b, name, gt=None):
    v = req_field(b, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request("Field %s must be a number" % name)
    if gt is not None and not v > gt:
        bad_request("Field %s must be > %s" % (name, gt))
    return v


# ------------------------------------------------------------ datetimes -----
def parse_dt(value, field="timestamp"):
    if not isinstance(value, str) or not value:
        bad_request("Field %s must be an ISO 8601 string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        bad_request("Field %s is not a valid ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, name):
    return parse_dt(req_field(b, name), name)
