"""Payload structural validation helpers (ERR_VALIDATION, HTTP 400)."""

from flask import request

import errors


def get_body():
    """Return the JSON request body as a dict; {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.validation("request body must be a JSON object")
    return data


def req_str(body, field):
    value = body.get(field)
    if value is None:
        raise errors.validation(f"missing required field: {field}")
    if not isinstance(value, str) or isinstance(value, bool):
        raise errors.validation(f"field {field} must be a string")
    return value


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, str) or isinstance(value, bool):
        raise errors.validation(f"field {field} must be a string")
    return value


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        raise errors.validation(f"field {field} must be one of {sorted(allowed)}")
    return value


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_bool(body, field):
    value = body.get(field)
    if not isinstance(value, bool):
        raise errors.validation(f"field {field} must be a boolean")
    return value


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise errors.validation(f"field {field} must be a boolean")
    return value


def req_int(body, field):
    value = body.get(field)
    if value is None:
        raise errors.validation(f"missing required field: {field}")
    if not isinstance(value, int) or isinstance(value, bool):
        raise errors.validation(f"field {field} must be an integer")
    return value


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, int) or isinstance(value, bool):
        raise errors.validation(f"field {field} must be an integer")
    return value


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.validation(f"field {field} must be a number")
    return value


def opt_str_list(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, list):
        raise errors.validation(f"field {field} must be an array")
    for item in value:
        if not isinstance(item, str):
            raise errors.validation(f"field {field} must contain only strings")
    return list(value)
