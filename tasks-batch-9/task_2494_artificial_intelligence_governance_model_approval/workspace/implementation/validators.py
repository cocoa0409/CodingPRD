"""Request body / query-string shape validation (rejection ladder step 8)."""
from datetime import datetime, timezone

from flask import request

import constants
from errors import bad_request

_MISSING = object()


def get_body():
    """Parse the JSON body. An absent body reads as an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        raise bad_request("request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise bad_request("request body must be a JSON object")
    return parsed


def _present(body, field):
    return field in body and body[field] is not None


def as_str(body, field, required=False, min_len=None, max_len=None, default=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, str):
        raise bad_request("%s must be a string" % field)
    if min_len is not None and len(value) < min_len:
        raise bad_request("%s must be at least %d characters" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s must be at most %d characters" % (field, max_len))
    return value


def as_bool(body, field, required=False, default=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean" % field)
    return value


def as_int(body, field, required=False, minimum=None, maximum=None, default=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("%s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be <= %s" % (field, maximum))
    return value


def as_number(body, field, required=False, default=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be a number" % field)
    return value


def as_enum(body, field, allowed, required=False, default=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def as_enum_list(body, field, allowed, required=False, default=None, allow_empty=True,
                 max_len=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, list):
        raise bad_request("%s must be an array" % field)
    if not allow_empty and len(value) == 0:
        raise bad_request("%s must not be empty" % field)
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s must contain at most %d entries" % (field, max_len))
    for entry in value:
        if not isinstance(entry, str) or entry not in allowed:
            raise bad_request("%s entries must be one of %s" % (field, ", ".join(allowed)))
    if len(set(value)) != len(value):
        raise bad_request("%s must not contain duplicates" % field)
    return list(value)


def as_str_list(body, field, required=False, default=None, min_len=None, max_len=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    value = body[field]
    if not isinstance(value, list):
        raise bad_request("%s must be an array" % field)
    if min_len is not None and len(value) < min_len:
        raise bad_request("%s must contain at least %d entries" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s must contain at most %d entries" % (field, max_len))
    for entry in value:
        if not isinstance(entry, str):
            raise bad_request("%s entries must be strings" % field)
    return list(value)


def parse_datetime(value, field):
    if not isinstance(value, str) or not value.strip():
        raise bad_request("%s must be an ISO 8601 UTC timestamp" % field)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("%s must be an ISO 8601 UTC timestamp" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def as_datetime(body, field, required=False, default=None):
    if not _present(body, field):
        if required:
            raise bad_request("%s is required" % field)
        return default
    return parse_datetime(body[field], field)


def pagination_params():
    limit = _query_int(
        "limit",
        constants.PAGINATION_LIMIT_DEFAULT,
        constants.PAGINATION_LIMIT_MIN,
        constants.PAGINATION_LIMIT_MAX,
    )
    offset = _query_int(
        "offset",
        constants.PAGINATION_OFFSET_DEFAULT,
        constants.PAGINATION_OFFSET_MIN,
        None,
    )
    return limit, offset


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise bad_request("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be <= %s" % (name, maximum))
    return value


def query_str(name):
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
    raise bad_request("%s must be true or false" % name)


def require_any_field(body, fields):
    if not any(field in body for field in fields):
        raise bad_request("at least one of %s must be supplied" % ", ".join(fields))
