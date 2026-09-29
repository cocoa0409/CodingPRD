"""Payload shape validation -- PRD 2.11 band 2 (ERR_INVALID_REQUEST / ERR_INVALID_INTERVAL)."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from errors import ApiError
from prec import q

_MISSING = object()

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def present(payload, name):
    return name in payload and payload[name] is not None


def raw(payload, name, default=None):
    if name in payload and payload[name] is not None:
        return payload[name]
    return default


def str_field(payload, name, required=True, min_len=1, max_len=None, pattern=None,
              default=None):
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("%s is shorter than the permitted minimum." % name)
    if max_len is not None and len(value) > max_len:
        bad("%s is longer than the permitted maximum." % name)
    if pattern is not None and not re.match(pattern, value):
        bad("%s is not correctly formatted." % name)
    return value


def int_field(payload, name, required=True, minimum=None, maximum=None, default=None):
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool):
        bad("%s must be an integer." % name)
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            bad("%s must be a whole number." % name)
        value = int(value)
    elif isinstance(value, float):
        if value != int(value):
            bad("%s must be a whole number." % name)
        value = int(value)
    elif not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s is below the permitted minimum." % name)
    if maximum is not None and value > maximum:
        bad("%s is above the permitted maximum." % name)
    return value


def num_field(payload, name, required=True, places=2, gt=None, ge=None, default=None):
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool):
        bad("%s must be numeric." % name)
    if not isinstance(value, (int, float, Decimal)):
        bad("%s must be numeric." % name)
    try:
        rounded = q(value, places)
    except (InvalidOperation, ValueError):
        bad("%s must be numeric." % name)
    if gt is not None and rounded <= q(gt, places):
        bad("%s must be greater than %s." % (name, gt))
    if ge is not None and rounded < q(ge, places):
        bad("%s must be at least %s." % (name, ge))
    return rounded


def bool_field(payload, name, required=False, default=None):
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def enum_field(payload, name, values, required=True, default=None):
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in values:
        bad("%s must be one of %s." % (name, ", ".join(values)))
    return value


def parse_instant(text, name="timestamp"):
    if not isinstance(text, str):
        bad("%s must be an RFC 3339 timestamp." % name)
    match = DT_RE.match(text.strip())
    if not match:
        bad("%s must be an RFC 3339 timestamp." % name)
    year, month, day, hour, minute, second, frac, offset = match.groups()
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        value = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        bad("%s must be an RFC 3339 timestamp." % name)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta_minutes = int(body[:2]) * 60 + int(body[2:])
        value = value - sign * _minutes(delta_minutes)
    return value


def _minutes(count):
    from datetime import timedelta

    return timedelta(minutes=count)


def instant_field(payload, name, required=True):
    """Returns (echoed_string, parsed_datetime)."""
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return None, None
    value = payload[name]
    parsed = parse_instant(value, name)
    return value, parsed


def date_field(payload, name, required=True):
    """Returns (echoed_string, parsed_date)."""
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return None, None
    value = payload[name]
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        bad("%s must be a YYYY-MM-DD calendar date." % name)
    parts = value.strip().split("-")
    try:
        parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        bad("%s must be a YYYY-MM-DD calendar date." % name)
    return value, parsed


def month_field(payload, name, required=True):
    if not present(payload, name):
        if required:
            bad("%s is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, str) or not MONTH_RE.match(value.strip()):
        bad("%s must be a YYYY-MM month." % name)
    month = int(value.strip().split("-")[1])
    if month < 1 or month > 12:
        bad("%s must be a YYYY-MM month." % name)
    return value


def parse_date_arg(text, name):
    if not isinstance(text, str) or not DATE_RE.match(text.strip()):
        bad("%s must be a YYYY-MM-DD calendar date." % name)
    parts = text.strip().split("-")
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        bad("%s must be a YYYY-MM-DD calendar date." % name)


def stored_instant(text):
    """Re-parse a stored datetime string for comparison against the clock."""
    if text is None:
        return None
    return parse_instant(text)
