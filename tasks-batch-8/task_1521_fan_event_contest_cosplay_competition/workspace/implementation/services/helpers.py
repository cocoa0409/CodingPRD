"""Shared request-validation helpers (priority 3 field-shape checks)."""

from datetime import datetime

from db import parse_iso
from errors import err_validation


def body_json():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def require_field(body, name):
    if name not in body or body[name] is None:
        raise err_validation(f"Missing required field: {name}")
    return body[name]


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise err_validation(f"Field {name} must be a string")
    return v


def req_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not v:
        raise err_validation(f"Field {name} must be a non-empty string")
    return v


def req_int(body, name, minimum=None, maximum=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err_validation(f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_validation(f"Field {name} must be <= {maximum}")
    return v


def req_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise err_validation(f"Field {name} must be a boolean")
    return v


def opt_bool(body, name, default=False):
    v = body.get(name, default)
    if not isinstance(v, bool):
        raise err_validation(f"Field {name} must be a boolean")
    return v


def req_enum(body, name, allowed):
    v = require_field(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_list(body, name, of_str=True, allow_empty=True):
    v = require_field(body, name)
    if not isinstance(v, list):
        raise err_validation(f"Field {name} must be a list")
    if not allow_empty and not v:
        raise err_validation(f"Field {name} must be non-empty")
    if of_str:
        for item in v:
            if not isinstance(item, str):
                raise err_validation(f"Field {name} must be a list of strings")
    return v


def opt_list(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, list):
        raise err_validation(f"Field {name} must be a list")
    for item in v:
        if not isinstance(item, str):
            raise err_validation(f"Field {name} must be a list of strings")
    return v


def req_iso(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise err_validation(f"Field {name} must be an ISO8601 timestamp string")
    try:
        parse_iso(v)
    except (ValueError, TypeError):
        raise err_validation(f"Field {name} is not a valid ISO8601 timestamp")
    return v


def req_date(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise err_validation(f"Field {name} must be a YYYY-MM-DD string")
    try:
        parts = v.split("-")
        if len(parts) != 3:
            raise ValueError
        datetime(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        raise err_validation(f"Field {name} is not a valid YYYY-MM-DD date")
    return v
