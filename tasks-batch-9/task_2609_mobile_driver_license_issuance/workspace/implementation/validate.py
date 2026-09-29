"""Request-schema conformance (rejection-ladder step 3)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError, bad_request

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def body():
    if request.method in ("POST", "PATCH", "PUT"):
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise bad_request("Request body must be a JSON object.")
        return data
    return {}


def present(payload, name):
    return name in payload and payload[name] is not None


# --------------------------------------------------------------------------
# scalar readers
# --------------------------------------------------------------------------
def req_str(payload, name, min_len=1, max_len=None):
    if not present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise bad_request("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(payload, name, default=None, min_len=1, max_len=None):
    if not present(payload, name):
        return default
    return req_str(payload, name, min_len, max_len)


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        raise bad_request(
            "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def req_int(payload, name, minimum=None, maximum=None):
    if not present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be at most %d." % (name, maximum))
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    return req_int(payload, name, minimum, maximum)


def req_bool(payload, name):
    if not present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % name)
    return value


def opt_bool(payload, name, default=False):
    if not present(payload, name):
        return default
    return req_bool(payload, name)


def req_array_str(payload, name):
    if not present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise bad_request("Field '%s' must be an array of strings." % name)
    return list(value)


def opt_array_str(payload, name, default=None):
    if not present(payload, name):
        return list(default) if default is not None else None
    return req_array_str(payload, name)


def parse_dt(value, name):
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Field '%s' must be an ISO 8601 datetime string." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("Field '%s' must be an ISO 8601 datetime." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(payload, name):
    if not present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    return parse_dt(payload[name], name)


def opt_dt(payload, name, default=None):
    if not present(payload, name):
        return default
    return parse_dt(payload[name], name)


def req_date(payload, name):
    value = req_str(payload, name)
    if not DATE_RE.match(value):
        raise bad_request("Field '%s' must be a YYYY-MM-DD calendar date." % name)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise bad_request("Field '%s' must be a valid calendar date." % name)


def opt_date(payload, name, default=None):
    if not present(payload, name):
        return default
    return req_date(payload, name)


def interval(start, end, start_name, end_name):
    if start >= end:
        raise bad_request(
            "Field '%s' must be strictly earlier than '%s'." % (start_name, end_name)
        )


# --------------------------------------------------------------------------
# query parameters
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
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed):
    value = q_str(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad_request(
            "Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def q_bool(name):
    value = q_str(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad_request("Query parameter '%s' must be a boolean." % name)


def not_found(error_id, message=None):
    return ApiError(error_id, message)
