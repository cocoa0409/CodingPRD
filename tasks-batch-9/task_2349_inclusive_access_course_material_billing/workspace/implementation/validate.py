"""Request body validation -- PRD 2.11 precedence step 3 (ERR_INVALID_REQUEST)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message=None):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body(allowed_fields=()):
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        body = {}
    else:
        try:
            body = request.get_json(force=True, silent=False)
        except Exception:
            bad("Request body is not valid JSON")
        if body is None:
            body = {}
    if not isinstance(body, dict):
        bad("Request body must be a JSON object")
    allowed = set(allowed_fields)
    for key in body.keys():
        if key not in allowed:
            bad("Unknown field: %s" % key)
    return body


def _supplied(body, name, required, default):
    if name not in body or body[name] is None:
        if required:
            bad("Missing required field: %s" % name)
        return False, default
    return True, None


def f_str(body, name, required=True, default=None, min_len=1, max_len=None, pattern=None):
    present, fallback = _supplied(body, name, required, default)
    if not present:
        return fallback
    value = body[name]
    if not isinstance(value, str):
        bad("Field %s must be a string" % name)
    if len(value) < min_len:
        bad("Field %s is too short" % name)
    if max_len is not None and len(value) > max_len:
        bad("Field %s is too long" % name)
    if pattern is not None and not re.match(pattern, value):
        bad("Field %s has an invalid format" % name)
    return value


def f_int(body, name, required=True, default=None, minimum=None, maximum=None):
    present, fallback = _supplied(body, name, required, default)
    if not present:
        return fallback
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("Field %s is below its minimum" % name)
    if maximum is not None and value > maximum:
        bad("Field %s is above its maximum" % name)
    return value


def f_num(body, name, required=True, default=None, minimum=None, maximum=None,
          exclusive_minimum=None):
    present, fallback = _supplied(body, name, required, default)
    if not present:
        return fallback
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field %s must be a number" % name)
    if minimum is not None and value < minimum:
        bad("Field %s is below its minimum" % name)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        bad("Field %s is below its minimum" % name)
    if maximum is not None and value > maximum:
        bad("Field %s is above its maximum" % name)
    return value


def f_enum(body, name, values, required=True, default=None):
    present, fallback = _supplied(body, name, required, default)
    if not present:
        return fallback
    value = body[name]
    if not isinstance(value, str) or value not in values:
        bad("Field %s is not a recognized enum member" % name)
    return value


def f_date(body, name, required=True, default=None):
    """Returns a datetime.date, or `default` when absent."""
    present, fallback = _supplied(body, name, required, default)
    if not present:
        return fallback
    value = body[name]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        bad("Field %s must be an ISO date in YYYY-MM-DD form" % name)
    try:
        return date.fromisoformat(value)
    except ValueError:
        bad("Field %s must be an ISO date in YYYY-MM-DD form" % name)


def f_datetime(body, name, required=True, default=None):
    present, fallback = _supplied(body, name, required, default)
    if not present:
        return fallback
    value = body[name]
    if not isinstance(value, str):
        bad("Field %s must be an ISO 8601 timestamp" % name)
    return parse_dt(value)


def parse_dt(value):
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("Timestamp is not a valid ISO 8601 instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
