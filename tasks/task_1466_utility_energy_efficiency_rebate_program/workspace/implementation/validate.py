"""Structural request-body validation helpers (ERR_INVALID_REQUEST, 400)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def get_body():
    """Parse the JSON request body; absent body reads as an empty object."""
    raw = request.get_data()
    if not raw:
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        _bad("Request body must be valid JSON")
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def req_str(body, field):
    v = body.get(field, None)
    if v is None:
        _bad("Missing required field: %s" % field)
    if not isinstance(v, str) or v == "":
        _bad("Field %s must be a non-empty string" % field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, None)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad("Field %s must be a string" % field)
    return v


def _check_int(v, field):
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field %s must be an integer" % field)
    return v


def _check_range(v, field, minimum, maximum):
    if minimum is not None and v < minimum:
        _bad("Field %s is out of range (minimum %s)" % (field, minimum))
    if maximum is not None and v > maximum:
        _bad("Field %s is out of range (maximum %s)" % (field, maximum))
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field, None)
    if v is None:
        _bad("Missing required field: %s" % field)
    _check_int(v, field)
    return _check_range(v, field, minimum, maximum)


def opt_int(body, field, default=None, minimum=None, maximum=None):
    v = body.get(field, None)
    if v is None:
        return default
    _check_int(v, field)
    return _check_range(v, field, minimum, maximum)


def opt_bool(body, field, default):
    v = body.get(field, None)
    if v is None:
        return default
    if not isinstance(v, bool):
        _bad("Field %s must be a boolean" % field)
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        _bad("Field %s must be one of %s" % (field, ", ".join(allowed)))
    return v


def req_date(body, field):
    """Validate a strict YYYY-MM-DD calendar date; returns the raw string."""
    v = req_str(body, field)
    return parse_date_str(v, field)


def parse_date_str(v, field="date"):
    if not isinstance(v, str) or not _DATE_RE.match(v):
        _bad("Field %s must be an ISO8601 date (YYYY-MM-DD)" % field)
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        _bad("Field %s is not a valid calendar date" % field)
    return v


def parse_iso_datetime(v, field="to_iso8601"):
    if not isinstance(v, str) or not v.strip():
        _bad("Field %s must be an ISO8601 timestamp" % field)
    s = v.strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _bad("Field %s must be an ISO8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
