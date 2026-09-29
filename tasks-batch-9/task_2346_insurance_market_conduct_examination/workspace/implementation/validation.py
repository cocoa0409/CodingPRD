"""Request-shape validation — band 6 of PRD §2.11 (ERR_INVALID_REQUEST)."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import request

from errors import invalid

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
NAIC_RE = re.compile(r"^\d{5}$")
RFC3339_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)

MIN_NARRATIVE_CHARS = 20


def body():
    """Parse the JSON body; a missing body is treated as an empty object."""
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise invalid("The request body must be a JSON object.")
    return parsed


def present(payload, key):
    return key in payload and payload[key] is not None


def _require_present(payload, key):
    if not present(payload, key):
        raise invalid("Field %s is required." % key)


def get_int(payload, key, required=True, default=None, minimum=None, maximum=None):
    if not present(payload, key):
        if required:
            _require_present(payload, key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field %s must be an integer." % key)
    if minimum is not None and value < minimum:
        raise invalid("Field %s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field %s must be at most %s." % (key, maximum))
    return value


def get_str(payload, key, required=True, default=None, min_len=1, max_len=None):
    if not present(payload, key):
        if required:
            _require_present(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        raise invalid("Field %s must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field %s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field %s must be at most %d characters." % (key, max_len))
    return value


def get_bool(payload, key, required=True, default=None):
    if not present(payload, key):
        if required:
            _require_present(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise invalid("Field %s must be a boolean." % key)
    return value


def get_enum(payload, key, allowed, required=True, default=None):
    if not present(payload, key):
        if required:
            _require_present(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        raise invalid(
            "Field %s must be one of %s." % (key, ", ".join(sorted(allowed)))
        )
    return value


def get_date(payload, key, required=True, default=None):
    if not present(payload, key):
        if required:
            _require_present(payload, key)
        return default
    value = payload[key]
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise invalid("Field %s must be a YYYY-MM-DD date." % key)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise invalid("Field %s must be a valid calendar date." % key)
    return value


def get_percentage(payload, key, required=True, default=None):
    """A percentage inside the inclusive range 0.00..100.00, carried to 2 decimals."""
    if not present(payload, key):
        if required:
            _require_present(payload, key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("Field %s must be a number." % key)
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        raise invalid("Field %s must be a number." % key)
    if decimal_value < Decimal("0") or decimal_value > Decimal("100"):
        raise invalid("Field %s must be between 0.00 and 100.00." % key)
    return decimal_value


def require_narrative(payload, key, required=True, default=None):
    """narrative / summary / public_summary / rebuttal_note: at least 20 chars."""
    value = get_str(payload, key, required=required, default=default, min_len=None)
    if value is None:
        return default
    if len(value) < MIN_NARRATIVE_CHARS:
        raise invalid("Field %s must be at least 20 characters." % key)
    return value


def require_state_code(payload, key):
    value = get_str(payload, key, required=True, min_len=None)
    if not STATE_CODE_RE.match(value):
        raise invalid("Field %s must be exactly two uppercase letters." % key)
    return value


def require_naic(payload, key):
    value = get_str(payload, key, required=True, min_len=None)
    if not NAIC_RE.match(value):
        raise invalid("Field %s must be exactly five digits." % key)
    return value


def require_after(later_value, earlier_value, later_key):
    if later_value <= earlier_value:
        raise invalid("Field %s must be strictly after the start date." % later_key)


def parse_rfc3339_utc(payload, key):
    """An RFC3339 UTC instant; a non-UTC offset is malformed."""
    value = get_str(payload, key, required=True, min_len=None)
    match = RFC3339_RE.match(value)
    if not match:
        raise invalid("Field %s must be an RFC3339 UTC instant." % key)
    offset = match.group(4)
    if offset not in ("Z", "z", "+00:00", "-00:00"):
        raise invalid("Field %s must be expressed in UTC." % key)
    fraction = match.group(3) or ""
    text = "%sT%s%s+00:00" % (match.group(1), match.group(2), fraction[:7])
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("Field %s must be an RFC3339 UTC instant." % key)
    return value, parsed
