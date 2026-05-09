"""Request body parsing & validation helpers."""
from flask import request

import errors as E


def get_json_body() -> dict:
    """Return JSON body. Empty body → {}; non-JSON → ERR_VALIDATION."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        E.validation_err("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        E.validation_err("Request body must be a JSON object")
    return body


def require_field(body: dict, field: str, type_check=None):
    if field not in body or body[field] is None:
        E.validation_err(f"Missing required field: {field}")
    val = body[field]
    if type_check is not None and not type_check(val):
        E.validation_err(f"Invalid type for field: {field}")
    return val


def require_string(body, field, min_len=None, max_len=None, allow_empty=False):
    val = require_field(body, field, lambda v: isinstance(v, str))
    if not allow_empty and not val.strip():
        E.validation_err(f"Field {field} must be non-empty")
    if min_len is not None and len(val) < min_len:
        E.validation_err(f"Field {field} too short")
    if max_len is not None and len(val) > max_len:
        E.validation_err(f"Field {field} too long")
    return val


def require_int(body, field, minv=None, maxv=None):
    val = require_field(body, field, lambda v: isinstance(v, int) and not isinstance(v, bool))
    if minv is not None and val < minv:
        E.validation_err(f"Field {field} below minimum")
    if maxv is not None and val > maxv:
        E.validation_err(f"Field {field} above maximum")
    return val


def require_enum(body, field, allowed):
    val = require_field(body, field, lambda v: isinstance(v, str))
    if val not in allowed:
        E.validation_err(f"Field {field} must be one of {sorted(allowed)}")
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        E.validation_err(f"Field {field} must be one of {sorted(allowed)}")
    return val


def require_bool(body, field):
    if field not in body or body[field] is None:
        E.validation_err(f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, bool):
        E.validation_err(f"Field {field} must be boolean")
    return val


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        E.validation_err(f"Field {field} must be boolean")
    return val


def require_array(body, field, item_check=None):
    val = require_field(body, field, lambda v: isinstance(v, list))
    if item_check is not None:
        for it in val:
            if not item_check(it):
                E.validation_err(f"Invalid item in array {field}")
    return val
