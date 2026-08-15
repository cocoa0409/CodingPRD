"""Shared helpers: response envelope, errors, auth, body validation, pagination."""
import random
import re
import string
from datetime import datetime, timezone, date
from decimal import Decimal, InvalidOperation

from flask import request, jsonify

ROLES = {"Generator", "Offtaker", "BrokerOps", "ComplianceOfficer", "PlatformAdmin"}
ALL_ROLES = None  # actor(None) means any declared role

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def now_ts():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_ts()}


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def created(data):
    return ok(data, 201)


def ok_list(items, page_meta):
    meta = _meta()
    meta.update(page_meta)
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# Error shortcuts
# ---------------------------------------------------------------------------

def bad_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def not_found(msg="Resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def fk_not_found(msg="Referenced entity does not exist"):
    raise ApiError("ERR_FK_NOT_FOUND", 422, msg)


def ownership_err():
    raise ApiError("ERR_OWNERSHIP_MISMATCH", 403, "Acting identity does not own this resource")


def invalid_state(msg="Requested transition is not declared from the current state"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


# ---------------------------------------------------------------------------
# Auth (stages 1-2 of the validation pipeline)
# ---------------------------------------------------------------------------

def actor(allowed_roles=ALL_ROLES):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Body validation (stage 4)
# ---------------------------------------------------------------------------

def raw_body():
    return request.get_json(silent=True)


def body_dict():
    b = raw_body()
    if not isinstance(b, dict):
        bad_request("Request body must be a JSON object")
    return b


def _req(body, name):
    if name not in body or body[name] is None:
        bad_request(f"Missing required field: {name}")
    return body[name]


def as_str(body, name):
    v = _req(body, name)
    if not isinstance(v, str) or not v:
        bad_request(f"Field {name} must be a non-empty string")
    return v


def as_dec(body, name):
    v = _req(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request(f"Field {name} must be a number")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        bad_request(f"Field {name} must be a number")


def as_int(body, name):
    v = _req(body, name)
    if isinstance(v, bool):
        bad_request(f"Field {name} must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    bad_request(f"Field {name} must be an integer")


def as_date(body, name):
    v = _req(body, name)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        bad_request(f"Field {name} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(v)
    except ValueError:
        bad_request(f"Field {name} must be an ISO date (YYYY-MM-DD)")


def as_enum(body, name, allowed):
    v = _req(body, name)
    if not isinstance(v, str) or v not in allowed:
        bad_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def as_str_list(body, name):
    v = _req(body, name)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        bad_request(f"Field {name} must be an array of strings")
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def paginate(items):
    raw_l = request.args.get("limit")
    raw_o = request.args.get("offset")
    if raw_l is None:
        limit = 10
    else:
        try:
            limit = int(raw_l)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        limit = min(max(limit, 1), 100)
    if raw_o is None:
        offset = 0
    else:
        try:
            offset = int(raw_o)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        offset = max(offset, 0)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def ser(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
