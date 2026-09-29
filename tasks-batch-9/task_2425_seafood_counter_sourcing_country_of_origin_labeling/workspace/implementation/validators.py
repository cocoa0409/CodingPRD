"""Body-field validation (PRD 2.9 item 19 -> ERR_INVALID_REQUEST, HTTP 400)."""

import re

from common import dec, parse_iso, rhu
from errors import fail

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
STORE_RE = re.compile(r"^[0-9]{4}$")


def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, allow_empty=False):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    value = body[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % field)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % field)
    return value


def opt_str(body, field, default=None, allow_empty=True):
    if not _present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % field)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % field)
    return value


def req_int(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (field, maximum))
    return value


def req_bool(body, field):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    value = body[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % field)
    return value


def req_number(body, field, places, minimum=None, maximum=None, exclusive_min=None):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return _number(body[field], field, places, minimum, maximum, exclusive_min)


def opt_number(body, field, places, default=None, minimum=None, exclusive_min=None):
    if not _present(body, field):
        return default
    return _number(body[field], field, places, minimum, None, exclusive_min)


def _number(value, field, places, minimum, maximum, exclusive_min):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % field)
    quantised = dec(value) if places is None else rhu(dec(value), places)
    if exclusive_min is not None and quantised <= dec(exclusive_min):
        fail("ERR_INVALID_REQUEST", "%s must be greater than %s." % (field, exclusive_min))
    if minimum is not None and quantised < dec(minimum):
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (field, minimum))
    if maximum is not None and quantised > dec(maximum):
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (field, maximum))
    return quantised


def req_enum(body, field, members):
    value = req_str(body, field)
    if value not in members:
        fail(
            "ERR_INVALID_REQUEST",
            "%s must be one of %s." % (field, ", ".join(sorted(members))),
        )
    return value


def opt_enum(body, field, members, default=None):
    if not _present(body, field):
        return default
    value = req_str(body, field)
    if value not in members:
        fail(
            "ERR_INVALID_REQUEST",
            "%s must be one of %s." % (field, ", ".join(sorted(members))),
        )
    return value


def req_datetime(body, field):
    value = req_str(body, field)
    parsed = parse_iso(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant." % field)
    return parsed


def req_str_array(body, field):
    if not _present(body, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    value = body[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % field)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            fail("ERR_INVALID_REQUEST", "%s must be an array of non-empty strings." % field)
    return list(value)


def req_store_number(body, field):
    value = req_str(body, field)
    if not STORE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be exactly 4 digits." % field)
    return value


def req_country(body, field):
    value = req_str(body, field)
    if not COUNTRY_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be 2 uppercase letters." % field)
    return value


def opt_country(body, field):
    if not _present(body, field):
        return None
    value = req_str(body, field)
    if not COUNTRY_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be 2 uppercase letters." % field)
    return value


def opt_id(body, field):
    """A body foreign key: present-but-not-a-string is treated as unresolvable."""
    if not _present(body, field):
        return None
    value = body[field]
    if not isinstance(value, str):
        return "\x00invalid"
    return value
