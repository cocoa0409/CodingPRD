"""Ladder rung 3: request-shape validation (types, enums, ranges, orderings)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGITS = re.compile(r"^\d+$")

MISSING = object()


def body():
    """The parsed JSON object of the request, or {} when no body was sent."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def req(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "%s is required." % name)
    return data[name]


# --------------------------------------------------------------------------- #
# scalars
# --------------------------------------------------------------------------- #
def string_field(data, name, required=True, default=None, allow_empty=False):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % name)
    return value


def int_field(data, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (name, maximum))
    return value


def bool_field(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def number_field(data, name, required=True, default=None, gt=None, lte=None, ge=None, lt=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    value = float(value)
    if gt is not None and not value > gt:
        fail("ERR_INVALID_REQUEST", "%s must be greater than %s." % (name, gt))
    if ge is not None and not value >= ge:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (name, ge))
    if lt is not None and not value < lt:
        fail("ERR_INVALID_REQUEST", "%s must be less than %s." % (name, lt))
    if lte is not None and not value <= lte:
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (name, lte))
    return value


def enum_field(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def date_field(data, name, required=True, default=None):
    """Returns the raw YYYY-MM-DD string after validating it."""
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date." % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be a valid calendar date." % name)
    return value


def digits_field(data, name, length, required=True, default=None):
    value = string_field(data, name, required=required, default=default)
    if value is None:
        return None
    if not _DIGITS.match(value) or len(value) != length:
        fail("ERR_INVALID_REQUEST", "%s must be exactly %d digits." % (name, length))
    return value


def month_list_field(data, name, required=True):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return None
    value = data[name]
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty array of months." % name)
    out = []
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, int):
            fail("ERR_INVALID_REQUEST", "%s entries must be integers 1..12." % name)
        if entry < 1 or entry > 12:
            fail("ERR_INVALID_REQUEST", "%s entries must be integers 1..12." % name)
        out.append(entry)
    return out


def id_list_field(data, name, required=True):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return None
    value = data[name]
    if not isinstance(value, list) or len(value) == 0:
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty array." % name)
    for entry in value:
        if not isinstance(entry, str) or entry.strip() == "":
            fail("ERR_INVALID_REQUEST", "%s entries must be non-empty strings." % name)
    return list(value)


def forbid(data, name, reason):
    if _present(data, name):
        fail("ERR_INVALID_REQUEST", reason)


# --------------------------------------------------------------------------- #
# date helpers
# --------------------------------------------------------------------------- #
def to_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def order_dates(first, second, strict, message):
    """`second` must be after (strict) or on-or-after `first`."""
    a = to_date(first)
    b = to_date(second)
    if strict:
        if not b > a:
            fail("ERR_INVALID_REQUEST", message)
    else:
        if not b >= a:
            fail("ERR_INVALID_REQUEST", message)


def parse_iso8601(value, name):
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % name)
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def month_of(value):
    return to_date(value).month


def year_of(value):
    return to_date(value).year


def first_of_month(year, month):
    return date(year, month, 1)
