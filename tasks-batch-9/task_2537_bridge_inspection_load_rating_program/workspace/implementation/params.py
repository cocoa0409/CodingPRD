"""Request body / query-string parsing and well-formedness checks (precedence step 3)."""

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import response
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body(required=False):
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            bad("A JSON request body is required.")
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


# --------------------------------------------------------------------------- #
# body fields
# --------------------------------------------------------------------------- #
def get_string(body, name, required=False, default=None, max_length=None, min_length=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if required and value.strip() == "":
        bad("Field '%s' must not be empty." % name)
    if min_length is not None and len(value) < min_length:
        bad("Field '%s' is too short." % name)
    if max_length is not None and len(value) > max_length:
        bad("Field '%s' is too long." % name)
    return value


def get_enum(body, name, allowed, required=False, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return value


def _as_decimal(name, value):
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    bad("Field '%s' must be a number." % name)


def get_number(
    body,
    name,
    required=False,
    default=None,
    minimum=None,
    maximum=None,
    exclusive_minimum=None,
    exclusive_maximum=None,
):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    number = _as_decimal(name, value)
    _range_check(name, number, minimum, maximum, exclusive_minimum, exclusive_maximum)
    return number


def get_int(
    body,
    name,
    required=False,
    default=None,
    minimum=None,
    maximum=None,
    exclusive_minimum=None,
    exclusive_maximum=None,
):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    if isinstance(value, bool):
        bad("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        number = value
    elif isinstance(value, Decimal):
        if number_is_integral(value):
            number = int(value)
        else:
            bad("Field '%s' must be an integer." % name)
    elif isinstance(value, float):
        if float(value).is_integer():
            number = int(value)
        else:
            bad("Field '%s' must be an integer." % name)
    else:
        bad("Field '%s' must be an integer." % name)
    _range_check(name, Decimal(number), minimum, maximum, exclusive_minimum, exclusive_maximum)
    return number


def number_is_integral(value):
    try:
        return value == value.to_integral_value()
    except (InvalidOperation, ValueError):
        return False


def _range_check(name, number, minimum, maximum, exclusive_minimum, exclusive_maximum):
    if minimum is not None and number < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and number > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s." % (name, maximum))
    if exclusive_minimum is not None and number <= Decimal(str(exclusive_minimum)):
        bad("Field '%s' must be > %s." % (name, exclusive_minimum))
    if exclusive_maximum is not None and number >= Decimal(str(exclusive_maximum)):
        bad("Field '%s' must be < %s." % (name, exclusive_maximum))


def get_bool(body, name, required=False, default=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def get_array(body, name, required=False, default=None, min_items=None):
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return default
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if min_items is not None and len(value) < min_items:
        bad("Field '%s' must contain at least %d entries." % (name, min_items))
    return value


# --------------------------------------------------------------------------- #
# datetimes
# --------------------------------------------------------------------------- #
def parse_instant(text, field="value"):
    """Parse an ISO 8601 instant; naive values are read as UTC."""
    if not isinstance(text, str) or text.strip() == "":
        bad("Field '%s' must be an ISO 8601 timestamp." % field)
    candidate = text.strip()
    normalised = candidate
    if normalised.endswith("Z") or normalised.endswith("z"):
        normalised = normalised[:-1] + "+00:00"
    normalised = normalised.replace(" ", "T", 1)
    parsed = None
    try:
        parsed = datetime.fromisoformat(normalised)
    except Exception:
        parsed = None
    if parsed is None:
        for pattern in (
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(normalised, pattern)
                break
            except ValueError:
                parsed = None
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_instant(body, name, required=False):
    """Return (raw_text, parsed_datetime). Client text is echoed back verbatim."""
    value = body.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("Field '%s' is required." % name)
        return None, None
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 timestamp string." % name)
    return value, parse_instant(value, name)


# --------------------------------------------------------------------------- #
# query string
# --------------------------------------------------------------------------- #
def query_pagination():
    limit = _query_int("limit", response.LIMIT_DEFAULT)
    offset = _query_int("offset", response.OFFSET_DEFAULT)
    if limit < response.LIMIT_MIN or limit > response.LIMIT_MAX:
        bad("Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def query_enum(name, allowed):
    raw = query_string(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of: %s." % (name, ", ".join(allowed)))
    return raw
