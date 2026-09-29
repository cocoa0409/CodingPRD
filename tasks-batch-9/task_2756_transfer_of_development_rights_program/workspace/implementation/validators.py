"""Request-shape validation (ladder rung 4) plus pagination and filter parsing."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from core import dec
from errors import bad_request

MISSING = object()


def body():
    """Parsed JSON object; a missing or non-JSON body behaves as an empty object."""
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad_request("request body must be a JSON object")
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def field_str(data, name, required=True, default=None, min_len=None, max_len=None):
    if not _present(data, name):
        if required:
            bad_request("missing required field %s" % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        bad_request("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad_request("%s is shorter than %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad_request("%s is longer than %d characters" % (name, max_len))
    return value


def field_enum(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            bad_request("missing required field %s" % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad_request("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def field_bool(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            bad_request("missing required field %s" % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad_request("%s must be a boolean" % name)
    return value


def field_int(data, name, required=True, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            bad_request("missing required field %s" % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad_request("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("%s must be <= %s" % (name, maximum))
    return value


def field_cents(data, name, required=True, default=None, minimum=0, maximum=None):
    """Every *_cents field is a non-negative integer (PRD 2.10 rung 4)."""
    return field_int(data, name, required=required, default=default, minimum=minimum, maximum=maximum)


def field_decimal(data, name, required=True, default=None, minimum=None, maximum=None,
                  places=2, exclusive_min=False):
    if not _present(data, name):
        if required:
            bad_request("missing required field %s" % name)
        return None if default is None else dec(default)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad_request("%s must be a number" % name)
    try:
        parsed = dec(repr(value) if isinstance(value, float) else value)
    except (InvalidOperation, ValueError):
        bad_request("%s must be a number" % name)
    parsed = parsed.normalize()
    exponent = parsed.as_tuple().exponent
    if places is not None and exponent < -places:
        bad_request("%s carries more than %d decimal places" % (name, places))
    if minimum is not None:
        if exclusive_min and parsed <= dec(minimum):
            bad_request("%s must be greater than %s" % (name, minimum))
        if not exclusive_min and parsed < dec(minimum):
            bad_request("%s must be >= %s" % (name, minimum))
    if maximum is not None and parsed > dec(maximum):
        bad_request("%s must be <= %s" % (name, maximum))
    return dec(value if not isinstance(value, float) else repr(value))


def parse_datetime(raw, name):
    if not isinstance(raw, str) or raw.strip() == "":
        bad_request("%s must be an ISO 8601 timestamp" % name)
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        try:
            value = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            bad_request("%s is not a valid ISO 8601 timestamp" % name)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def field_datetime(data, name, required=True, default=None, nullable=False):
    if name not in data or data[name] is None:
        if name in data and data[name] is None and nullable:
            return None
        if required:
            bad_request("missing required field %s" % name)
        return default
    return parse_datetime(data[name], name)


def field_str_list(data, name, required=False, default=None, min_len=None, max_len=None):
    if not _present(data, name):
        if required:
            bad_request("missing required field %s" % name)
        return list(default) if default is not None else None
    value = data[name]
    if not isinstance(value, list):
        bad_request("%s must be an array of strings" % name)
    for item in value:
        if not isinstance(item, str):
            bad_request("%s must be an array of strings" % name)
        if min_len is not None and len(item) < min_len:
            bad_request("%s entries are too short" % name)
        if max_len is not None and len(item) > max_len:
            bad_request("%s entries are too long" % name)
    return list(value)


# ---------------------------------------------------------------------------
# Pagination and filters (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def filter_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def filter_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        bad_request("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def filter_bool(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value in ("true", "True", "TRUE", "1"):
        return True
    if value in ("false", "False", "FALSE", "0"):
        return False
    bad_request("%s must be a boolean" % name)


def filter_int(name):
    if name not in request.args:
        return None
    try:
        return int(str(request.args.get(name)).strip())
    except (TypeError, ValueError):
        bad_request("%s must be an integer" % name)
