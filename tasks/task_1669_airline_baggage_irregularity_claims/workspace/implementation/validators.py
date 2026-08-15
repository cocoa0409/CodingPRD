"""Request body shape validation per PRD §2.10 step 4."""

from datetime import date

from errors import ApiError, ERR_INVALID_REQUEST


def bad_request(msg: str):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def get_json_body():
    from flask import request
    if not request.is_json:
        bad_request("Request body must be JSON")
    body = request.get_json(silent=True)
    if body is None:
        bad_request("Request body must be valid JSON")
    if not isinstance(body, dict):
        bad_request("Request body must be a JSON object")
    return body


def ensure_no_unknown_fields(body: dict, allowed: set):
    extras = set(body.keys()) - allowed
    if extras:
        bad_request(f"Unknown or system-supplied fields: {sorted(extras)}")


def require_fields(body: dict, fields):
    for f in fields:
        if f not in body:
            bad_request(f"Missing required field: {f}")


def as_str(value, name):
    if not isinstance(value, str):
        bad_request(f"Field {name} must be a string")
    return value


def as_nonempty_str(value, name):
    if not isinstance(value, str) or not value:
        bad_request(f"Field {name} must be a non-empty string")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        bad_request(f"Field {name} must be a boolean")
    return value


def as_int(value, name, min_value=None, max_value=None):
    # bool is a subclass of int; reject it explicitly
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request(f"Field {name} must be an integer")
    if min_value is not None and value < min_value:
        bad_request(f"Field {name} must be >= {min_value}")
    if max_value is not None and value > max_value:
        bad_request(f"Field {name} must be <= {max_value}")
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        bad_request(f"Field {name} must be one of {sorted(allowed)}")
    return value


def as_str_array(value, name, allow_empty=False):
    if not isinstance(value, list):
        bad_request(f"Field {name} must be an array")
    if not allow_empty and len(value) == 0:
        bad_request(f"Field {name} must be non-empty")
    for i, item in enumerate(value):
        if not isinstance(item, str):
            bad_request(f"Field {name}[{i}] must be a string")
    return value


def as_date_str(value, name):
    """Validate YYYY-MM-DD strictly."""
    if not isinstance(value, str):
        bad_request(f"Field {name} must be a date string YYYY-MM-DD")
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        bad_request(f"Field {name} must be YYYY-MM-DD")
    try:
        y = int(value[0:4]); m = int(value[5:7]); d = int(value[8:10])
        date(y, m, d)
    except ValueError:
        bad_request(f"Field {name} must be a valid YYYY-MM-DD date")
    return value


def as_iso_datetime_str(value, name):
    """Validate ISO-8601 datetime with timezone."""
    if not isinstance(value, str):
        bad_request(f"Field {name} must be an ISO-8601 datetime string")
    from util import iso_to_ms
    try:
        iso_to_ms(value)
    except Exception:
        bad_request(f"Field {name} must be a valid ISO-8601 datetime")
    return value


def as_tag_number(value, name="tag_number"):
    if not isinstance(value, str):
        bad_request(f"Field {name} must be a string")
    if len(value) != 10 or not value.isdigit():
        bad_request(f"Field {name} must be exactly 10 digits")
    return value
