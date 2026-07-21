"""Request-body validation helpers (ERR_INVALID_REQUEST, priority 4)."""

from flask import request

from errors import bad_request
import store


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise bad_request(f"Missing or invalid field: {field}")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise bad_request(f"Invalid field: {field}")
    return v


def req_enum(body, field, choices):
    v = req_str(body, field)
    if v not in choices:
        raise bad_request(f"Invalid enum value for {field}: {v}")
    return v


def req_int(body, field, min_value=None):
    if field not in body or body[field] is None:
        raise bad_request(f"Missing field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise bad_request(f"Field {field} must be >= {min_value}")
    return v


def opt_int(body, field, min_value=None):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"Field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise bad_request(f"Field {field} must be >= {min_value}")
    return v


def req_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise bad_request(f"Missing field: {field}")
    v = body[field]
    if not isinstance(v, bool):
        raise bad_request(f"Field {field} must be a boolean")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise bad_request(f"Field {field} must be a boolean")
    return v


def req_dt(body, field):
    v = req_str(body, field)
    store.parse_dt(v)  # raises ERR_INVALID_REQUEST if unparseable
    return v


def opt_dt(body, field):
    v = opt_str(body, field)
    if v is not None:
        store.parse_dt(v)
    return v
