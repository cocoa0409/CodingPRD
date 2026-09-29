"""Request schema validation — ladder tier 3, ERR_INVALID_REQUEST (PRD 2.6)."""
import re
from datetime import datetime, timezone

from flask import request

import errors

MISSING = object()


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


def _present(data, name):
    return name in data and data[name] is not None


def get_str(data, name, required=True, default=None, min_len=1, max_len=None,
            pattern=None):
    if not _present(data, name):
        if required:
            raise errors.invalid_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        raise errors.invalid_request("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise errors.invalid_request("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        raise errors.invalid_request("Field '%s' is too long." % name)
    if pattern is not None and re.fullmatch(pattern, value) is None:
        raise errors.invalid_request("Field '%s' does not match its pattern." % name)
    return value


def get_int(data, name, required=True, default=None, minimum=None,
            exclusive_minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            raise errors.invalid_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not _is_int(value):
        raise errors.invalid_request("Field '%s' must be an integer." % name)
    _check_bounds(name, value, minimum, exclusive_minimum, maximum)
    return value


def get_num(data, name, required=True, default=None, minimum=None,
            exclusive_minimum=None, maximum=None):
    if not _present(data, name):
        if required:
            raise errors.invalid_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not _is_num(value):
        raise errors.invalid_request("Field '%s' must be a number." % name)
    _check_bounds(name, value, minimum, exclusive_minimum, maximum)
    return value


def _check_bounds(name, value, minimum, exclusive_minimum, maximum):
    if minimum is not None and value < minimum:
        raise errors.invalid_request("Field '%s' is below its minimum." % name)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise errors.invalid_request("Field '%s' must be greater than %s."
                                     % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        raise errors.invalid_request("Field '%s' is above its maximum." % name)


def get_bool(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            raise errors.invalid_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise errors.invalid_request("Field '%s' must be a boolean." % name)
    return value


def get_enum(data, name, domain, required=True, default=None):
    if not _present(data, name):
        if required:
            raise errors.invalid_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in domain:
        raise errors.invalid_request("Field '%s' is outside its declared domain." % name)
    return value


def get_enum_list(data, name, domain, required=True, default=None,
                  non_empty=True):
    if not _present(data, name):
        if required:
            raise errors.invalid_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, list):
        raise errors.invalid_request("Field '%s' must be an array." % name)
    if non_empty and len(value) == 0:
        raise errors.invalid_request("Field '%s' must not be empty." % name)
    for item in value:
        if not isinstance(item, str) or item not in domain:
            raise errors.invalid_request(
                "Field '%s' contains a value outside its declared domain." % name)
    return list(value)


def parse_datetime(raw, name):
    if not isinstance(raw, str) or raw.strip() == "":
        raise errors.invalid_request("Field '%s' must be an ISO 8601 timestamp." % name)
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise errors.invalid_request("Field '%s' must be an ISO 8601 timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_datetime(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            raise errors.invalid_request("Field '%s' is required." % name)
        return default
    return parse_datetime(data[name], name)


def get_id(data, name, required=True, default=None):
    return get_str(data, name, required=required, default=default, min_len=1)


# ---------------------------------------------------------------- query params
def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0). PRD 2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise errors.invalid_request("Query parameter 'offset' must not be negative.")
    return limit, offset


def qs_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def qs_enum(name, domain):
    value = qs_str(name)
    if value is None:
        return None
    if value not in domain:
        raise errors.invalid_request(
            "Query parameter '%s' is outside its declared domain." % name)
    return value


def qs_datetime(name):
    value = qs_str(name)
    if value is None:
        return None
    return parse_datetime(value, name)
