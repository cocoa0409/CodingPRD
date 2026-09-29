"""Request-shape validation (ladder step 3 -> ERR_INVALID_REQUEST) and pagination."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body; an absent body is an empty object."""
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad("Request body must be a valid JSON object.")
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _present(payload, name):
    return name in payload and payload[name] is not None


def req_present(payload, name):
    if name not in payload or payload[name] is None:
        bad("Field '%s' is required." % name)


def string_field(payload, name, min_len=1, max_len=None, pattern=None,
                 required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        bad("Field '%s' is malformed." % name)
    return value


def id_field(payload, name, required=True):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, str) or len(value) == 0:
        bad("Field '%s' must be a non-empty string." % name)
    return value


def int_field(payload, name, minimum=None, maximum=None, choices=None,
              required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    if choices is not None and value not in choices:
        bad("Field '%s' must be one of %s." % (name, list(choices)))
    return value


def number_field(payload, name, minimum=None, maximum=None, exclusive_min=None,
                 required=True, default=None):
    """Numeric field returned as Decimal built from the literal text."""
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % name)
    if not dec.is_finite():
        bad("Field '%s' must be a finite number." % name)
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be at most %s." % (name, maximum))
    return dec


def enum_field(payload, name, choices, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in choices:
        bad("Field '%s' must be one of %s." % (name, list(choices)))
    return value


def bool_field(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def date_field(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        bad("Field '%s' must be an ISO calendar date (YYYY-MM-DD)." % name)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        bad("Field '%s' must be an ISO calendar date (YYYY-MM-DD)." % name)


def parse_iso_datetime(value, name):
    if not isinstance(value, str) or len(value) == 0:
        bad("Field '%s' must be an ISO 8601 datetime." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 datetime." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def datetime_field(payload, name, required=True, default=None):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return default
    return parse_iso_datetime(payload[name], name)


def array_field(payload, name, min_len=None, required=True):
    if not _present(payload, name):
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must contain at least %d entries." % (name, min_len))
    return value


def is_monday(value):
    return value.weekday() == 0


# ---------------------------------------------------------------- pagination

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?\d+$", raw.strip()):
        bad("Query parameter '%s' must be an integer." % name)
    return int(raw.strip())


def pagination():
    limit = _query_int("limit", PAGINATION_DEFAULT_LIMIT)
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET)
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        bad("Query parameter 'limit' must be between %d and %d."
            % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if offset < PAGINATION_MIN_OFFSET:
        bad("Query parameter 'offset' must be at least %d." % PAGINATION_MIN_OFFSET)
    return limit, offset


def query_enum(name, choices):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in choices:
        bad("Query parameter '%s' must be one of %s." % (name, list(choices)))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
