"""Request-shape validation helpers — PRD §2.8 step 4 (ERR_VALIDATION)."""

import re

from flask import request

from db import parse_iso
from errors import ApiError

UPC_RE = re.compile(r"^\d{12}$")
ISRC_RE = re.compile(r"^[A-Za-z0-9]{12}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def bad(message="Invalid request body."):
    raise ApiError("ERR_VALIDATION", message)


def body():
    """Parsed JSON object body; a non-object or unparseable body is ERR_VALIDATION."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        bad("Missing required field '%s'." % field)
    return data[field]


def req_string(data, field, min_len=1, max_len=None):
    value = require(data, field)
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if len(value) < min_len:
        bad("Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % field)
    return value


def opt_string(data, field, min_len=1, max_len=None, nullable=True):
    if field not in data:
        return None, False
    value = data[field]
    if value is None:
        if not nullable:
            bad("Field '%s' may not be null." % field)
        return None, True
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if len(value) < min_len:
        bad("Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % field)
    return value, True


def as_int(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below its minimum." % field)
    if maximum is not None and value > maximum:
        bad("Field '%s' is above its maximum." % field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    return as_int(require(data, field), field, minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, nullable=False):
    if field not in data:
        return None, False
    value = data[field]
    if value is None:
        if not nullable:
            bad("Field '%s' may not be null." % field)
        return None, True
    return as_int(value, field, minimum, maximum), True


def as_bool(value, field):
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, nullable=False):
    if field not in data:
        return None, False
    value = data[field]
    if value is None:
        if not nullable:
            bad("Field '%s' may not be null." % field)
        return None, True
    return as_bool(value, field), True


def req_bool(data, field):
    return as_bool(require(data, field), field)


def req_enum(data, field, allowed):
    value = require(data, field)
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, field, allowed, nullable=False):
    if field not in data:
        return None, False
    value = data[field]
    if value is None:
        if not nullable:
            bad("Field '%s' may not be null." % field)
        return None, True
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value, True


def req_datetime(data, field):
    value = require(data, field)
    return as_datetime(value, field)


def as_datetime(value, field):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 string." % field)
    try:
        return parse_iso(value)
    except Exception:
        bad("Field '%s' must be an ISO 8601 instant." % field)


def opt_datetime(data, field, nullable=True):
    if field not in data:
        return None, False
    value = data[field]
    if value is None:
        if not nullable:
            bad("Field '%s' may not be null." % field)
        return None, True
    return as_datetime(value, field), True


def check_upc(value):
    if value is not None and not UPC_RE.match(value):
        bad("upc must be exactly 12 digits.")
    return value


def check_isrc(value):
    if value is not None and not ISRC_RE.match(value):
        bad("isrc must be exactly 12 alphanumeric characters.")
    return value


def check_country(value):
    if value is not None and not COUNTRY_RE.match(value):
        bad("country_code must be exactly 2 uppercase letters.")
    return value


def req_id(data, field):
    value = require(data, field)
    if not isinstance(value, str) or not value:
        bad("Field '%s' must be a non-empty string identifier." % field)
    return value
