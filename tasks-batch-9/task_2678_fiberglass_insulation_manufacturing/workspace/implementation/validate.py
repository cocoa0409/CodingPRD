"""Request shape validation (ladder rung 5) and typed field readers.

Unknown fields and server-derived fields present in a payload are ignored,
never rejected (PRD 2.8 rung 5).
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

MISSING = object()


def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def present(payload, field):
    return field in payload and payload[field] is not None


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def to_decimal(value, field):
    if isinstance(value, bool):
        _bad(field, "must be a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            _bad(field, "must be a number")
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            _bad(field, "must be a number")
        if not parsed.is_finite():
            _bad(field, "must be a finite number")
        return parsed
    _bad(field, "must be a number")


def dec_field(payload, field, required=True, gt=None, ge=None, lt=None, le=None, default=MISSING):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return None if default is MISSING else default
    value = to_decimal(payload[field], field)
    if gt is not None and not value > gt:
        _bad(field, "must be greater than %s" % gt)
    if ge is not None and not value >= ge:
        _bad(field, "must be greater than or equal to %s" % ge)
    if lt is not None and not value < lt:
        _bad(field, "must be less than %s" % lt)
    if le is not None and not value <= le:
        _bad(field, "must be less than or equal to %s" % le)
    return value


def int_field(payload, field, required=True, minimum=None, maximum=None, default=MISSING):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return None if default is MISSING else default
    value = payload[field]
    if isinstance(value, bool):
        _bad(field, "must be an integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, float):
        if not float(value).is_integer():
            _bad(field, "must be an integer")
        parsed = int(value)
    elif isinstance(value, str):
        text = value.strip()
        try:
            parsed = int(text, 10)
        except (TypeError, ValueError):
            _bad(field, "must be an integer")
    else:
        _bad(field, "must be an integer")
    if minimum is not None and parsed < minimum:
        _bad(field, "must be at least %d" % minimum)
    if maximum is not None and parsed > maximum:
        _bad(field, "must be at most %d" % maximum)
    return parsed


def bool_field(payload, field, required=True, default=MISSING):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return None if default is MISSING else default
    value = payload[field]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "false"):
            return text == "true"
    _bad(field, "must be a boolean")


def str_field(payload, field, required=True, allowed=None, default=MISSING, allow_empty=False):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return None if default is MISSING else default
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(field, "must be a non-empty string")
    if allowed is not None and value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def id_field(payload, field, required=True):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be a non-empty string")
    return value


def parse_instant(value, field):
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be an RFC3339 UTC instant")
    text = value.strip()
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        _bad(field, "must be an RFC3339 UTC instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return text, parsed.astimezone(timezone.utc)


def instant_field(payload, field, required=True):
    """Returns (raw_string, aware_datetime) so responses can echo exactly what
    the caller supplied while comparisons run on real instants."""
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return None, None
    return parse_instant(payload[field], field)


def list_field(payload, field, required=True):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return None
    value = payload[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    return value


def absent(payload, field, message):
    if field in payload and payload[field] is not None:
        fail("ERR_INVALID_REQUEST", message)
