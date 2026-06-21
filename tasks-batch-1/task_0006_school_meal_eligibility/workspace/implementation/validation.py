"""Pagination & request-body validation helpers."""
from flask import request
from errors import ERR_INVALID_PAGINATION, ERR_INVALID_REQUEST, raise_err


def parse_pagination():
    """Returns (limit, offset). Validates per PRD §2.3 / validation priority 15."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_PAGINATION, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_PAGINATION, "limit must be in [1,100]")
    if offset < 0:
        raise_err(ERR_INVALID_PAGINATION, "offset must be >= 0")
    return limit, offset


def get_json_body() -> dict:
    """Return the parsed JSON request body (empty dict if absent). Reject non-object."""
    if request.method in ("GET", "DELETE"):
        return {}
    if request.content_length is None or request.content_length == 0:
        return {}
    try:
        body = request.get_json(silent=False, force=False)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def enforce_keys(body: dict, required: set, optional: set):
    """Reject missing required keys or unknown keys."""
    allowed = set(required) | set(optional)
    body_keys = set(body.keys())
    missing = required - body_keys
    if missing:
        raise_err(ERR_INVALID_REQUEST, f"missing required fields: {sorted(missing)}")
    unknown = body_keys - allowed
    if unknown:
        raise_err(ERR_INVALID_REQUEST, f"unknown fields: {sorted(unknown)}")


def require_type(value, types, field_name):
    if not isinstance(value, types):
        raise_err(ERR_INVALID_REQUEST, f"field {field_name} has wrong type")


def require_int(value, field_name, *, min_val=None, max_val=None):
    # Bools are technically ints — reject them
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, f"field {field_name} must be integer")
    if min_val is not None and value < min_val:
        raise_err(ERR_INVALID_REQUEST, f"field {field_name} below minimum")
    if max_val is not None and value > max_val:
        raise_err(ERR_INVALID_REQUEST, f"field {field_name} above maximum")


def require_str(value, field_name, *, non_empty=True):
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, f"field {field_name} must be string")
    if non_empty and value == "":
        raise_err(ERR_INVALID_REQUEST, f"field {field_name} must be non-empty")


def require_bool(value, field_name):
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, f"field {field_name} must be boolean")
