"""Request-body shape validation (validation stage 3 -> ERR_VALIDATION_FAILED)."""
from flask import request

from errors import raise_error, ERR_VALIDATION_FAILED
from util import parse_dt


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_VALIDATION_FAILED, "request body must be a JSON object")
    return body


def _missing(body: dict, name: str) -> bool:
    return name not in body or body[name] is None


def _bad(name: str, extra: str = ""):
    raise_error(ERR_VALIDATION_FAILED, f"field '{name}' is invalid{': ' + extra if extra else ''}")


def req_str(body: dict, name: str) -> str:
    if _missing(body, name) or not isinstance(body[name], str):
        _bad(name, "required string")
    return body[name]


def opt_str(body: dict, name: str, default=None):
    if _missing(body, name):
        return default
    if not isinstance(body[name], str):
        _bad(name, "must be a string")
    return body[name]


def req_int(body: dict, name: str) -> int:
    if _missing(body, name) or isinstance(body[name], bool) or not isinstance(body[name], int):
        _bad(name, "required integer")
    return body[name]


def opt_int(body: dict, name: str, default=None):
    if _missing(body, name):
        return default
    if isinstance(body[name], bool) or not isinstance(body[name], int):
        _bad(name, "must be an integer")
    return body[name]


def req_bool(body: dict, name: str) -> bool:
    if _missing(body, name) or not isinstance(body[name], bool):
        _bad(name, "required boolean")
    return body[name]


def opt_bool(body: dict, name: str, default=None):
    if _missing(body, name):
        return default
    if not isinstance(body[name], bool):
        _bad(name, "must be a boolean")
    return body[name]


def req_number(body: dict, name: str):
    if _missing(body, name) or isinstance(body[name], bool) or not isinstance(body[name], (int, float)):
        _bad(name, "required number")
    return body[name]


def opt_number(body: dict, name: str, default=None):
    if _missing(body, name):
        return default
    if isinstance(body[name], bool) or not isinstance(body[name], (int, float)):
        _bad(name, "must be a number")
    return body[name]


def req_enum(body: dict, name: str, allowed) -> str:
    if _missing(body, name) or not isinstance(body[name], str) or body[name] not in allowed:
        _bad(name, f"must be one of {sorted(allowed)}")
    return body[name]


def opt_enum(body: dict, name: str, allowed, default=None):
    if _missing(body, name):
        return default
    if not isinstance(body[name], str) or body[name] not in allowed:
        _bad(name, f"must be one of {sorted(allowed)}")
    return body[name]


def req_dt(body: dict, name: str):
    if _missing(body, name):
        _bad(name, "required datetime")
    try:
        return parse_dt(body[name])
    except (ValueError, TypeError):
        _bad(name, "unparseable datetime")


def req_version(body: dict, name: str) -> int:
    """OCC version field: non-optional, integer-coercible (PRD 2.7)."""
    if _missing(body, name):
        _bad(name, "required version")
    value = body[name]
    if isinstance(value, bool):
        _bad(name, "must be an integer version")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    _bad(name, "must be an integer version")


def check_window_order(start, end) -> None:
    """Wherever a time window is supplied, scheduled_end strictly after scheduled_start."""
    if end <= start:
        raise_error(ERR_VALIDATION_FAILED, "scheduled_end must be strictly after scheduled_start")
