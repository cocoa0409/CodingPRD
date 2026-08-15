"""Shared helpers: ids, timestamps, common fields, body validation primitives."""
import uuid
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_QUANTITY
import clock


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity, with_common=True):
    """Set id/created_at/updated_at/version on a new entity dict."""
    entity["id"] = new_id()
    now = clock.now_iso()
    entity["created_at"] = now
    if with_common:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version (counts as modification per PRD §2.4)."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] = entity.get("version", 0) + 1


def get_json_body(required=True):
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def req_field(data, name):
    if name not in data or data[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    return data[name]


def req_string(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a non-empty string")
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
    return v


def opt_string(data, name, default=None):
    v = data.get(name, default)
    if v is not None and not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be a string")
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_array(data, name):
    v = req_field(data, name)
    if not isinstance(v, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an array")
    return v


def req_positive_int(data, name, quantity_error=True):
    """Integer quantity > 0 -> ERR_INVALID_QUANTITY (tier 2)."""
    if name not in data or data[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {name}")
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        if quantity_error:
            raise ApiError(ERR_INVALID_QUANTITY, 400, f"Field {name} must be a positive integer")
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be an integer")
    if v <= 0:
        if quantity_error:
            raise ApiError(ERR_INVALID_QUANTITY, 400, f"Field {name} must be greater than zero")
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field {name} must be positive")
    return v


def positive_int_value(v, name):
    """Validate a bare value (from nested arrays) as integer > 0 -> ERR_INVALID_QUANTITY."""
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_QUANTITY, 400, f"Field {name} must be a positive integer")
    if v <= 0:
        raise ApiError(ERR_INVALID_QUANTITY, 400, f"Field {name} must be greater than zero")
    return v
