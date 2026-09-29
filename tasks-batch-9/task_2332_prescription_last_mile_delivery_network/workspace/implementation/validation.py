"""Body / query parsing and field validation — rung 9 of the evaluation ladder."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import api_error

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DIGITS4_RE = re.compile(r"^\d{4}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")


def invalid(message):
    return api_error("ERR_INVALID_REQUEST", message)


def json_body():
    """Strictly parse the request body; an absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        raise invalid("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


def soft_body():
    """Best-effort body parse used by scope rules that must run before rung 9."""
    parsed = request.get_json(force=True, silent=True)
    return parsed if isinstance(parsed, dict) else {}


def present(body, name):
    return name in body and body[name] is not None


# --------------------------------------------------------------------------
# scalar field validators
# --------------------------------------------------------------------------
def string_field(body, name, required=True, default=None, min_len=1, max_len=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise invalid("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def int_field(body, name, required=True, default=None, minimum=None, maximum=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be <= %d." % (name, maximum))
    return value


def bool_field(body, name, required=False, default=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % name)
    return value


def enum_field(body, name, allowed, required=True, default=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def decimal_field(body, name, required=True, default=None, minimum=None, maximum=None,
                  max_places=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise invalid("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise invalid("Field '%s' must be a number." % name)
    if not dec.is_finite():
        raise invalid("Field '%s' must be a finite number." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise invalid("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        raise invalid("Field '%s' must be <= %s." % (name, maximum))
    if max_places is not None:
        exponent = dec.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -max_places:
            raise invalid("Field '%s' must carry at most %d decimal places." % (name, max_places))
    return dec


def parse_instant(text):
    """Parse an ISO 8601 UTC instant; returns a timezone-aware UTC datetime."""
    if not isinstance(text, str):
        return None
    value = text.strip()
    if ":" not in value:
        return None
    if value.endswith("Z") or value.endswith("z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def datetime_field(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    parsed = parse_instant(body[name])
    if parsed is None:
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


def date_field(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise invalid("Field '%s' must be an ISO calendar date (YYYY-MM-DD)." % name)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise invalid("Field '%s' must be an ISO calendar date (YYYY-MM-DD)." % name)
    return value


def string_array_field(body, name, required=True, default=None, min_items=1,
                       min_len=1, max_len=None):
    if not present(body, name):
        if required:
            raise invalid("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % name)
    if len(value) < min_items:
        raise invalid("Field '%s' must contain at least %d entry." % (name, min_items))
    for item in value:
        if not isinstance(item, str):
            raise invalid("Field '%s' must contain only strings." % name)
        if len(item) < min_len or (max_len is not None and len(item) > max_len):
            raise invalid("Entries of '%s' must be %s..%s characters."
                          % (name, min_len, max_len))
    return list(value)


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' must be 0 or greater.")
    return limit, offset


def query_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_enum(name, allowed):
    value = query_string(name)
    if value is None:
        return None
    if value not in allowed:
        raise invalid("Query parameter '%s' must be one of %s."
                      % (name, ", ".join(sorted(allowed))))
    return value


def query_int(name):
    value = query_string(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer." % name)
