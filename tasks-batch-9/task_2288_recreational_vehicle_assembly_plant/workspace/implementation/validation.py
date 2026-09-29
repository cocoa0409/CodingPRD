"""Schema validation — band 3 of the ladder (PRD §2.8). Everything here is
ERR_INVALID_REQUEST (400).
"""
import json
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError, bad_request

_MISSING = object()


def body_dict():
    """Parse the request body. An absent/empty body is an empty object."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        raise bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object.")
    return parsed


def _raw(body, name):
    """Undeclared keys are ignored by callers; explicit null counts as absent."""
    if name not in body:
        return _MISSING
    value = body[name]
    if value is None:
        return _MISSING
    return value


def _require(body, name, required):
    value = _raw(body, name)
    if value is _MISSING and required:
        raise bad_request("Field '{}' is required.".format(name))
    return value


def field_string(body, name, required=False, default=None, min_len=None, max_len=None):
    value = _require(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise bad_request("Field '{}' must be a string.".format(name))
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '{}' is shorter than {} characters.".format(name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '{}' is longer than {} characters.".format(name, max_len))
    return value


def field_enum(body, name, allowed, required=False, default=None):
    value = _require(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '{}' must be one of {}.".format(name, ", ".join(allowed)))
    return value


def field_int(body, name, required=False, default=None, minimum=None, maximum=None, allowed=None):
    value = _require(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '{}' must be an integer.".format(name))
    if minimum is not None and value < minimum:
        raise bad_request("Field '{}' must be at least {}.".format(name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '{}' must be at most {}.".format(name, maximum))
    if allowed is not None and value not in allowed:
        raise bad_request(
            "Field '{}' must be one of {}.".format(name, ", ".join(str(a) for a in allowed))
        )
    return value


def field_number(
    body,
    name,
    required=False,
    default=None,
    minimum=None,
    exclusive_minimum=None,
    max_decimals=2,
):
    """A station-hour style field: at most `max_decimals` decimal places (PRD §2.6)."""
    value = _require(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("Field '{}' must be a number.".format(name))
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise bad_request("Field '{}' must be a number.".format(name))
    if max_decimals is not None and -dec.as_tuple().exponent > max_decimals:
        raise bad_request(
            "Field '{}' carries more than {} decimal places.".format(name, max_decimals)
        )
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        raise bad_request("Field '{}' must be greater than {}.".format(name, exclusive_minimum))
    if minimum is not None and dec < Decimal(str(minimum)):
        raise bad_request("Field '{}' must be at least {}.".format(name, minimum))
    return dec


def field_bool(body, name, required=False, default=None):
    value = _require(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        raise bad_request("Field '{}' must be a boolean.".format(name))
    return value


def field_datetime(body, name, required=False, default=None):
    value = _require(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise bad_request("Field '{}' must be an ISO 8601 timestamp string.".format(name))
    parsed = db.parse_instant(value)
    if parsed is None:
        raise bad_request("Field '{}' is not a valid ISO 8601 timestamp.".format(name))
    return parsed


def field_str_array(body, name, required=False, default=None, allow_empty=True):
    value = _require(body, name, required)
    if value is _MISSING:
        return list(default) if default is not None else None
    if not isinstance(value, list):
        raise bad_request("Field '{}' must be an array.".format(name))
    for item in value:
        if not isinstance(item, str):
            raise bad_request("Field '{}' must contain only strings.".format(name))
    if not allow_empty and len(value) == 0:
        raise bad_request("Field '{}' must not be empty.".format(name))
    if len(set(value)) != len(value):
        raise bad_request("Field '{}' must not contain duplicate entries.".format(name))
    return list(value)


def field_enum_array(body, name, allowed, required=False, default=None, allow_empty=True):
    value = field_str_array(body, name, required=required, default=default, allow_empty=allow_empty)
    if value is None:
        return None
    for item in value:
        if item not in allowed:
            raise bad_request(
                "Field '{}' members must be one of {}.".format(name, ", ".join(allowed))
            )
    return value


# ---------------------------------------------------------------------------
# pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except ValueError:
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except ValueError:
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be zero or greater.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise bad_request("Query parameter '{}' must be one of {}.".format(name, ", ".join(allowed)))
    return value


def query_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad_request("Query parameter '{}' must be a boolean.".format(name))


def query_datetime(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    parsed = db.parse_instant(value)
    if parsed is None:
        raise bad_request("Query parameter '{}' is not a valid ISO 8601 timestamp.".format(name))
    return parsed


def unique_or_400(collection, field, value, label=None):
    for row in collection.values():
        if row.get(field) == value:
            raise bad_request("{} '{}' is already registered.".format(label or field, value))
