"""Response envelope, error handling, auth, pagination, money helpers."""
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify, g

from store import STORE

ROLES = {"StateAdmin", "Holder", "Owner", "RecoveryAgent", "StateExaminer", "StateApprover"}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
    }
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def err_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# ---- Auth / RBAC ----

def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(*allowed):
    """Decorator: authenticate then check the role is permitted for this endpoint."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---- Request body helpers ----

def get_json():
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object.")
    return data


def require_fields(body, *names):
    for n in names:
        if n not in body or body[n] is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {n}.")


def require_str(body, name):
    require_fields(body, name)
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a non-empty string.")
    return v


def require_int(body, name, min_val=None):
    require_fields(body, name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be an integer.")
    if min_val is not None and v < min_val:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be >= {min_val}.")
    return v


def require_enum(body, name, choices):
    v = require_str(body, name)
    if v not in choices:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be one of {sorted(choices)}.")
    return v


def require_bool(body, name):
    require_fields(body, name)
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a boolean.")
    return v


def require_number(body, name):
    require_fields(body, name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {name} must be a number.")
    return v


# ---- Pagination ----

def paginate(items):
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer.")
        if limit_v < 1:
            limit_v = 1
        if limit_v > 100:
            limit_v = 100
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer.")
        if offset_v < 0:
            offset_v = 0
    total = len(items)
    page = items[offset_v:offset_v + limit_v]
    return page, limit_v, offset_v, total


# ---- Money ----

def round_half_up(value):
    """Round a Decimal/number to the nearest integer, half up. Returns int."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(x):
    return Decimal(str(x))


# ---- Common entity field management ----

def stamp_new(entity, full=True):
    now = STORE.iso_now()
    entity["created_at"] = now
    entity["_seq"] = STORE.next_seq()
    if full:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    if "version" in entity:
        entity["updated_at"] = STORE.iso_now()
        entity["version"] = entity["version"] + 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def serialize_list(entities):
    ordered = sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))
    return ordered
