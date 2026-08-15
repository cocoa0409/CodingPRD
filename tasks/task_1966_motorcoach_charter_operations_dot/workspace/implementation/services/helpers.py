"""Shared helpers: pagination, validation, common field mutation."""

from flask import request

import db
import errors


def get_pagination():
    """Parse limit/offset query params. Defaults per spec."""
    try:
        limit = int(request.args.get("limit", "10"))
    except ValueError:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


def touch(entity: dict):
    """Refresh updated_at and increment version."""
    entity["updated_at"] = db.iso_now()
    entity["version"] = entity.get("version", 1) + 1


def now_iso() -> str:
    return db.iso_now()


def require_fields(payload: dict, *names):
    if payload is None:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "request body is required")
    for n in names:
        if n not in payload or payload[n] is None:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {n}")


def get_str(payload, name, required=False, allow_empty=False, default=None):
    v = payload.get(name)
    if v is None:
        if required:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    if not isinstance(v, str):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be a string")
    if not allow_empty and required and not v:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be non-empty")
    return v


def get_int(payload, name, required=False, default=None):
    v = payload.get(name)
    if v is None:
        if required:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be an integer")
    return v


def get_float(payload, name, required=False, default=None):
    v = payload.get(name)
    if v is None:
        if required:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be a number")
    return float(v)


def get_bool(payload, name, required=False, default=None):
    v = payload.get(name)
    if v is None:
        if required:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    if not isinstance(v, bool):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be a boolean")
    return v


def get_enum(payload, name, choices, required=False, default=None):
    v = payload.get(name)
    if v is None:
        if required:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    if v not in choices:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be one of {sorted(choices)}")
    return v


def get_datetime(payload, name, required=False):
    v = payload.get(name)
    if v is None:
        if required:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {name}")
        return None
    try:
        return db.parse_iso(v)
    except Exception:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be an ISO 8601 datetime")


def get_list(payload, name, required=False, default=None):
    v = payload.get(name)
    if v is None:
        if required:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    if not isinstance(v, list):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, f"{name} must be an array")
    return v


def check_customer_ownership(user_id: str, role: str, resource_customer_id: str):
    """When role is Customer, verify resource belongs to that customer."""
    if role == "Customer":
        if user_id != resource_customer_id:
            raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
