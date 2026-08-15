"""Request-body well-formedness validators (validation priority 4).

Each validator raises ERR_INVALID_REQUEST (400) on missing required fields,
wrong types, or out-of-range enum values.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import err_invalid_request
from timeutil import parse_datetime


def body():
    """Return the JSON object body; absent body is treated as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def _missing(d, name):
    return name not in d or d[name] is None


def req_str(d, name):
    if _missing(d, name) or not isinstance(d[name], str) or not d[name]:
        raise err_invalid_request(f"{name} is required and must be a string")
    return d[name]


def opt_str(d, name, default=None):
    if name not in d:
        return default
    if d[name] is not None and not isinstance(d[name], str):
        raise err_invalid_request(f"{name} must be a string")
    return d[name]


def req_number(d, name):
    if _missing(d, name) or isinstance(d[name], bool) or not isinstance(d[name], (int, float)):
        raise err_invalid_request(f"{name} is required and must be a number")
    return Decimal(str(d[name]))


def opt_number(d, name, default=None):
    if name not in d or d[name] is None:
        return default
    if isinstance(d[name], bool) or not isinstance(d[name], (int, float)):
        raise err_invalid_request(f"{name} must be a number")
    return Decimal(str(d[name]))


def req_int(d, name):
    if _missing(d, name) or isinstance(d[name], bool) or not isinstance(d[name], int):
        raise err_invalid_request(f"{name} is required and must be an integer")
    return d[name]


def opt_int(d, name, default=None):
    if name not in d or d[name] is None:
        return default
    if isinstance(d[name], bool) or not isinstance(d[name], int):
        raise err_invalid_request(f"{name} must be an integer")
    return d[name]


def req_bool(d, name):
    if _missing(d, name) or not isinstance(d[name], bool):
        raise err_invalid_request(f"{name} is required and must be a boolean")
    return d[name]


def opt_bool(d, name, default=False):
    if name not in d or d[name] is None:
        return default
    if not isinstance(d[name], bool):
        raise err_invalid_request(f"{name} must be a boolean")
    return d[name]


def req_enum(d, name, values):
    v = req_str(d, name)
    if v not in values:
        raise err_invalid_request(f"{name} must be one of {sorted(values)}")
    return v


def opt_enum(d, name, values, default=None):
    if name not in d or d[name] is None:
        return default
    if not isinstance(d[name], str) or d[name] not in values:
        raise err_invalid_request(f"{name} must be one of {sorted(values)}")
    return d[name]


def req_datetime(d, name):
    if _missing(d, name) or not isinstance(d[name], str):
        raise err_invalid_request(f"{name} is required and must be an ISO8601 timestamp")
    dt = parse_datetime(d[name])
    if dt is None:
        raise err_invalid_request(f"{name} must be an ISO8601 timestamp")
    return dt


def opt_datetime(d, name, default=None):
    if name not in d or d[name] is None:
        return default
    if not isinstance(d[name], str):
        raise err_invalid_request(f"{name} must be an ISO8601 timestamp")
    dt = parse_datetime(d[name])
    if dt is None:
        raise err_invalid_request(f"{name} must be an ISO8601 timestamp")
    return dt


def req_str_list(d, name, non_empty=False):
    if _missing(d, name) or not isinstance(d[name], list):
        raise err_invalid_request(f"{name} is required and must be an array")
    for item in d[name]:
        if not isinstance(item, str):
            raise err_invalid_request(f"{name} entries must be strings")
    if non_empty and len(d[name]) == 0:
        raise err_invalid_request(f"{name} must not be empty")
    return d[name]


def opt_str_list(d, name, default=None):
    if name not in d or d[name] is None:
        return default
    if not isinstance(d[name], list):
        raise err_invalid_request(f"{name} must be an array")
    for item in d[name]:
        if not isinstance(item, str):
            raise err_invalid_request(f"{name} entries must be strings")
    return d[name]


def req_number_list(d, name):
    if _missing(d, name) or not isinstance(d[name], list):
        raise err_invalid_request(f"{name} is required and must be an array")
    out = []
    for item in d[name]:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise err_invalid_request(f"{name} entries must be numbers")
        out.append(Decimal(str(item)))
    return out


def occ_field(d, name, required=False):
    """An optimistic-concurrency version field: integer when supplied."""
    if name not in d or d[name] is None:
        if required:
            raise err_invalid_request(f"{name} is required")
        return None
    return req_int(d, name)
