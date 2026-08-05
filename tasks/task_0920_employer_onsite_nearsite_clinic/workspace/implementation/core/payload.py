"""Rung 7 payload primitives (PRD 2.6 rung 7 -> ERR_VALIDATION).

Every helper here reports ERR_VALIDATION and nothing else; enum membership is
a separate rung and lives in ladder.rung8_enum.
"""

from .errors import ApiError
from . import timeutil


def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


def present(body, field):
    return field in body and body[field] is not None


def require_present(body, field):
    if not present(body, field):
        _fail("Field '%s' is required." % field)
    return body[field]


def require_absent(body, field, why=""):
    if present(body, field):
        _fail("Field '%s' must be null%s." % (field, (" " + why) if why else ""))


def require_string(body, field, min_len=None, max_len=None):
    value = require_present(body, field)
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % field)
    if min_len is not None and len(value) < min_len:
        _fail("Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        _fail("Field '%s' is too long." % field)
    return value


def optional_string(body, field):
    if not present(body, field):
        return None
    value = body[field]
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % field)
    return value


def require_bool(body, field):
    value = require_present(body, field)
    if not isinstance(value, bool):
        _fail("Field '%s' must be a boolean." % field)
    return value


def optional_bool(body, field, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, bool):
        _fail("Field '%s' must be a boolean." % field)
    return value


def require_int(body, field, minimum=None):
    value = require_present(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %d." % (field, minimum))
    return value


def optional_number(body, field):
    if not present(body, field):
        return None
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("Field '%s' must be a number." % field)
    return value


def optional_int(body, field, minimum=None):
    if not present(body, field):
        return None
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        _fail("Field '%s' must be at least %d." % (field, minimum))
    return value


def require_date(body, field):
    value = require_present(body, field)
    parsed = timeutil.parse_date(value)
    if parsed is None:
        _fail("Field '%s' must be an ISO date (YYYY-MM-DD)." % field)
    return parsed


def optional_date(body, field):
    if not present(body, field):
        return None
    parsed = timeutil.parse_date(body[field])
    if parsed is None:
        _fail("Field '%s' must be an ISO date (YYYY-MM-DD)." % field)
    return parsed


def require_instant(body, field):
    value = require_present(body, field)
    parsed = timeutil.parse_instant(value)
    if parsed is None:
        _fail("Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed


def require_string_array(body, field):
    value = require_present(body, field)
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        _fail("Field '%s' must be an array of strings." % field)
    return value


def optional_string_array(body, field, default=None):
    if not present(body, field):
        return default
    return require_string_array(body, field)


def require_weekday_array(body, field):
    value = require_present(body, field)
    if not isinstance(value, list) or not value:
        _fail("Field '%s' must be a non-empty array of ISO weekday numbers." % field)
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, int) or entry < 1 or entry > 7:
            _fail("Field '%s' must contain ISO weekday numbers 1..7." % field)
    return value


def optional_weekday_array(body, field, default=None):
    if not present(body, field):
        return default
    return require_weekday_array(body, field)


def require_hhmm(body, field):
    value = require_present(body, field)
    if timeutil.parse_hhmm(value) is None:
        _fail("Field '%s' must be an HH:MM 24-hour UTC wall time." % field)
    return value


def optional_hhmm(body, field):
    if not present(body, field):
        return None
    if timeutil.parse_hhmm(body[field]) is None:
        _fail("Field '%s' must be an HH:MM 24-hour UTC wall time." % field)
    return body[field]


def require_date_array(body, field):
    value = require_present(body, field)
    if not isinstance(value, list):
        _fail("Field '%s' must be an array of ISO dates." % field)
    for entry in value:
        if timeutil.parse_date(entry) is None:
            _fail("Field '%s' must contain ISO dates (YYYY-MM-DD)." % field)
    return value


def optional_date_array(body, field, default=None):
    if not present(body, field):
        return default
    return require_date_array(body, field)


def require_id(body, field):
    value = require_present(body, field)
    if not isinstance(value, str):
        _fail("Field '%s' must be a string identifier." % field)
    return value


def optional_id(body, field):
    if not present(body, field):
        return None
    value = body[field]
    if not isinstance(value, str):
        _fail("Field '%s' must be a string identifier." % field)
    return value
