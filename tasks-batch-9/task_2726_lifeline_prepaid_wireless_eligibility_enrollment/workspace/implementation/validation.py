"""Body schema validation. Every failure here is ERR_INVALID_REQUEST (422).

Computed and system fields that appear in a request body are silently ignored
(PRD section 2.7): these helpers only look at the keys they are asked about.
"""
import re

from flask import request

import db
from errors import ApiError

_MISSING = object()


def bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def get_body():
    body = request.get_json(silent=True, force=True)
    if body is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw is not None and raw.strip() != "":
            bad("Request body is not valid JSON")
        return {}
    if not isinstance(body, dict):
        bad("Request body must be a JSON object")
    return body


def present(body, key):
    return key in body and body[key] is not None


def _fetch(body, key, required):
    if key not in body or body[key] is None:
        if required:
            bad("Field '%s' is required" % key)
        return _MISSING
    return body[key]


def string_field(body, key, required=True, min_len=1, max_len=None,
                 pattern=None, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is shorter than %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is longer than %d characters" % (key, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("Field '%s' does not match the required format" % key)
    return value


def int_field(body, key, required=True, minimum=None, maximum=None, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' is below the permitted minimum" % key)
    if maximum is not None and value > maximum:
        bad("Field '%s' exceeds the permitted maximum" % key)
    return value


def bool_field(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % key)
    return value


def enum_field(body, key, allowed, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of: %s" % (key, ", ".join(allowed)))
    return value


def datetime_field(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 timestamp string" % key)
    parsed = db.parse_dt(value)
    if parsed is None:
        bad("Field '%s' is not a valid ISO 8601 timestamp" % key)
    return parsed


def date_field(body, key, required=True, default=None):
    """A YYYY-MM-DD calendar date, returned verbatim as supplied."""
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD date string" % key)
    if db.parse_date_only(value) is None:
        bad("Field '%s' is not a valid YYYY-MM-DD date" % key)
    return value


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def month_field(body, key, required=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM month string" % key)
    m = _MONTH_RE.match(value)
    if not m or not (1 <= int(m.group(2)) <= 12):
        bad("Field '%s' must be a valid YYYY-MM month" % key)
    return value


def string_list_field(body, key, required=True, item_pattern=None,
                      min_items=1, distinct=True, default=None):
    value = _fetch(body, key, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % key)
    if min_items is not None and len(value) < min_items:
        bad("Field '%s' must contain at least %d item(s)" % (key, min_items))
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must contain only strings" % key)
        if item_pattern is not None and not re.match(item_pattern, item):
            bad("Field '%s' contains an item in the wrong format" % key)
    if distinct:
        seen = [i.upper() for i in value]
        if len(set(seen)) != len(seen):
            bad("Field '%s' must contain distinct values" % key)
    return value
