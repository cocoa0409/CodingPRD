"""Rank-4 request shape validation helpers (PRD 2.5 / 2.3)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

MISSING = object()


def bad(message):
    return ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], message)


def get_body():
    raw = request.get_data()
    if not raw:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise bad("Request body must be valid JSON")
    if not isinstance(body, dict):
        raise bad("Request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_string(body, name, min_len=1, max_len=None):
    if not _present(body, name):
        raise bad("Field '%s' is required" % name)
    value = body[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string" % name)
    if len(value) < min_len:
        raise bad("Field '%s' must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters" % (name, max_len))
    return value


def opt_string(body, name, default=None, min_len=1, max_len=None):
    if not _present(body, name):
        return default
    return req_string(body, name, min_len=min_len, max_len=max_len)


def req_enum(body, name, allowed):
    if not _present(body, name):
        raise bad("Field '%s' is required" % name)
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_int(body, name, minimum=None, maximum=None, choices=None):
    if not _present(body, name):
        raise bad("Field '%s' is required" % name)
    value = body[name]
    if not _is_int(value):
        raise bad("Field '%s' must be an integer" % name)
    if choices is not None and value not in choices:
        raise bad("Field '%s' must be one of %s" % (name, sorted(choices)))
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s" % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None, choices=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum, choices=choices)


def req_number(body, name, minimum=None, exclusive_minimum=None):
    if not _present(body, name):
        raise bad("Field '%s' is required" % name)
    value = body[name]
    if not _is_num(value):
        raise bad("Field '%s' must be a number" % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise bad("Field '%s' must be a number" % name)
    if not dec.is_finite():
        raise bad("Field '%s' must be a finite number" % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        raise bad("Field '%s' must be >= %s" % (name, minimum))
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        raise bad("Field '%s' must be > %s" % (name, exclusive_minimum))
    return dec


def req_array(body, name, allowed=None, non_empty=True, unique=False):
    if not _present(body, name):
        raise bad("Field '%s' is required" % name)
    return _check_array(body[name], name, allowed, non_empty, unique)


def opt_array(body, name, default=None, allowed=None, non_empty=False, unique=False):
    if not _present(body, name):
        return list(default) if default is not None else None
    return _check_array(body[name], name, allowed, non_empty, unique)


def _check_array(value, name, allowed, non_empty, unique):
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array" % name)
    if non_empty and len(value) == 0:
        raise bad("Field '%s' must be a non-empty array" % name)
    for item in value:
        if not isinstance(item, str):
            raise bad("Field '%s' must be an array of strings" % name)
        if allowed is not None and item not in allowed:
            raise bad("Field '%s' contains an unrecognised member '%s'" % (name, item))
    if unique and len(set(value)) != len(value):
        raise bad("Field '%s' must not contain duplicates" % name)
    return list(value)


def parse_iso(raw, name):
    if not isinstance(raw, str):
        raise bad("Field '%s' must be an ISO 8601 timestamp string" % name)
    text = raw.strip()
    if not text:
        raise bad("Field '%s' must be an ISO 8601 timestamp string" % name)
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 timestamp string" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(body, name):
    if not _present(body, name):
        raise bad("Field '%s' is required" % name)
    return body[name], parse_iso(body[name], name)


def opt_datetime(body, name):
    if not _present(body, name):
        return None, None
    return req_datetime(body, name)


def pagination():
    def read(name, default, minimum, maximum):
        raw = request.args.get(name)
        if raw is None or raw == "":
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter '%s' must be an integer" % name)
        if value < minimum:
            raise bad("Query parameter '%s' must be >= %d" % (name, minimum))
        if maximum is not None and value > maximum:
            raise bad("Query parameter '%s' must be <= %d" % (name, maximum))
        return value

    return read("limit", 10, 1, 100), read("offset", 0, 0, None)


def filter_value(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def filter_enum(name, allowed):
    raw = filter_value(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise bad("Query parameter '%s' must be one of %s" % (name, sorted(allowed)))
    return raw


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
