"""Typed payload extraction — every failure is ERR_INVALID_REQUEST (PRD §2.10.4)."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from errors import fail

MISSING = object()


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def present(payload, field):
    return field in payload and payload[field] is not None


def req_string(payload, field, min_len=1, max_len=None, upper=False):
    if not present(payload, field):
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    if upper and value != value.upper():
        _bad(field, "must be uppercase")
    return value


def opt_string(payload, field, min_len=1, max_len=None, upper=False, default=None):
    if not present(payload, field):
        return default
    return req_string(payload, field, min_len, max_len, upper)


def req_int(payload, field, minimum=None, maximum=None):
    if not present(payload, field):
        _bad(field, "is required")
    return _as_int(payload[field], field, minimum, maximum)


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if not present(payload, field):
        return default
    return _as_int(payload[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %d" % maximum)
    return value


def req_decimal(payload, field, minimum=None, exclusive_min=None, places=None):
    if not present(payload, field):
        _bad(field, "is required")
    return _as_decimal(payload[field], field, minimum, exclusive_min, places)


def opt_decimal(payload, field, minimum=None, exclusive_min=None, places=None, default=None):
    if not present(payload, field):
        return default
    return _as_decimal(payload[field], field, minimum, exclusive_min, places)


def _as_decimal(value, field, minimum, exclusive_min, places):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(field, "must be a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")
    if number != number:  # NaN
        _bad(field, "must be a number")
    if minimum is not None and number < Decimal(str(minimum)):
        _bad(field, "must be >= %s" % minimum)
    if exclusive_min is not None and number <= Decimal(str(exclusive_min)):
        _bad(field, "must be > %s" % exclusive_min)
    if places is not None:
        from calc import rhu

        number = rhu(number, places)
    return number


def req_bool(payload, field):
    if not present(payload, field):
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(payload, field, default=False):
    if not present(payload, field):
        return default
    return req_bool(payload, field)


def req_enum(payload, field, allowed):
    value = req_string(payload, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(payload, field, allowed, default=None):
    if not present(payload, field):
        return default
    return req_enum(payload, field, allowed)


def parse_datetime(value, field):
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be an ISO 8601 datetime")
    raw = value.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        _bad(field, "must be an ISO 8601 datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(payload, field):
    if not present(payload, field):
        _bad(field, "is required")
    return parse_datetime(payload[field], field)


def opt_datetime(payload, field, default=None):
    if not present(payload, field):
        return default
    return parse_datetime(payload[field], field)


def req_date(payload, field):
    if not present(payload, field):
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        _bad(field, "must be an ISO 8601 date (YYYY-MM-DD)")


def req_id(payload, field):
    return req_string(payload, field, min_len=1)


def req_string_array(payload, field, min_items=1, max_items=None):
    if not present(payload, field):
        _bad(field, "is required")
    value = payload[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if len(value) < min_items:
        _bad(field, "must carry at least %d entries" % min_items)
    if max_items is not None and len(value) > max_items:
        _bad(field, "must carry at most %d entries" % max_items)
    for entry in value:
        if not isinstance(entry, str) or entry.strip() == "":
            _bad(field, "entries must be non-empty strings")
    return list(value)


def req_object_array(payload, field, max_items=None):
    value = payload.get(field)
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if max_items is not None and len(value) > max_items:
        _bad(field, "must carry at most %d entries" % max_items)
    for entry in value:
        if not isinstance(entry, dict):
            _bad(field, "entries must be objects")
    return list(value)
