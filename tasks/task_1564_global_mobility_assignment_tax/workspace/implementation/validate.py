"""Request body validation helpers (validation priority 3 existence, 4 shape)."""
import calendar
import re
from datetime import date

from flask import request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body() -> dict:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def require_path_resource(collection, rid):
    rec = db[collection].get(rid)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{collection[:-1]} not found: {rid}")
    return rec


def require_fk(collection, value, field):
    rec = db[collection].get(value)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"{field} references a non-existent resource: {value}")
    return rec


def req_field(body, name):
    if name not in body or body[name] is None:
        raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
    return body[name]


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise_error(ERR_INVALID_REQUEST, f"{name} must be a non-empty string")
    return v


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or v == "":
        raise_error(ERR_INVALID_REQUEST, f"{name} must be a non-empty string")
    return v


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return _checked_int(body[name], name, minimum, maximum)


def req_int(body, name, minimum=None, maximum=None):
    return _checked_int(req_field(body, name), name, minimum, maximum)


def _checked_int(v, name, minimum, maximum):
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise_error(ERR_INVALID_REQUEST, f"{name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise_error(ERR_INVALID_REQUEST, f"{name} must be <= {maximum}")
    return v


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"{name} must be a boolean")
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"{name} must be a boolean")
    return v


def req_enum(body, name, choices):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in choices:
        raise_error(ERR_INVALID_REQUEST, f"{name} must be one of {sorted(choices)}")
    return v


def req_date(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise_error(ERR_INVALID_REQUEST, f"{name} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"{name} is not a valid calendar date")


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]
