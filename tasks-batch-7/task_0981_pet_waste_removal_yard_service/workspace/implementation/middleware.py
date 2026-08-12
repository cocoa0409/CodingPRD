"""Auth header extraction, role checking, body parsing, and field validation.

Auth scheme (PRD section 2.1): every request carries X-User-ID and X-User-Role.
Roles are exactly: Customer, Technician, OperationsManager, BillingAdmin.
"""
from flask import request

from clock import parse_dt
from errors import (
    ApiError,
    err_unauthenticated,
    err_unauthorized,
    err_invalid_request,
    err_not_found,
    err_ref_not_found,
)

ROLES = {"Customer", "Technician", "OperationsManager", "BillingAdmin"}


def auth(*allowed_roles):
    """Validate auth headers (priority 1) then endpoint role permission (priority 2).
    Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise err_unauthenticated()
    if allowed_roles and role not in allowed_roles:
        raise err_unauthorized()
    return uid, role


def get_body():
    """Parse a JSON object body. Empty body -> {}. Non-object JSON -> 400."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_invalid_request("Malformed JSON body")
    return data


def _type_ok(value, typ):
    if typ is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if typ is bool:
        return isinstance(value, bool)
    if typ is str:
        return isinstance(value, str)
    if typ is list:
        return isinstance(value, list)
    if typ is (int,):  # unused
        return True
    return True


def require(data, field, typ=None):
    if field not in data or data[field] is None:
        raise err_invalid_request(f"Missing required field: {field}")
    v = data[field]
    if typ is not None and not _type_ok(v, typ):
        raise err_invalid_request(f"Field {field} has wrong type")
    return v


def optional(data, field, typ=None, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if typ is not None and not _type_ok(v, typ):
        raise err_invalid_request(f"Field {field} has wrong type")
    return v


def require_dt(data, field):
    v = require(data, field, str)
    try:
        return parse_dt(v)
    except ValueError:
        raise err_invalid_request(f"Field {field} is not a valid ISO 8601 datetime")


def optional_dt(data, field):
    v = optional(data, field, str)
    if v is None:
        return None
    try:
        return parse_dt(v)
    except ValueError:
        raise err_invalid_request(f"Field {field} is not a valid ISO 8601 datetime")


def require_enum(data, field, allowed):
    v = require(data, field, str)
    if v not in allowed:
        raise err_invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def optional_enum(data, field, allowed, default=None):
    v = optional(data, field, str)
    if v is None:
        return default
    if v not in allowed:
        raise err_invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def lookup(store, entity_id, label="Resource"):
    """Path-parameter resolution -> 404."""
    rec = store.get(entity_id)
    if rec is None:
        raise err_not_found(f"{label} {entity_id} not found")
    return rec


def lookup_fk(store, entity_id, label="Resource"):
    """Body foreign-key resolution -> 422."""
    rec = store.get(entity_id)
    if rec is None:
        raise err_ref_not_found(f"{label} {entity_id} does not exist")
    return rec


def parse_pagination():
    """limit (default 10, min 1, max 100), offset (default 0)."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ascending (insertion order tiebreak), then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], total
