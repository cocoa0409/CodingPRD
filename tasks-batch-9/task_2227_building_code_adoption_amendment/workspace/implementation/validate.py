"""Request-shape validation (ladder priority 4) and pagination (priority 5)."""
import re
from datetime import datetime, timedelta, timezone

from flask import request

import config
from errors import ApiError

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})"
    r"(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(?:(Z|z)|([+-])(\d{2}):?(\d{2}))?$"
)


def bad_request(message="Request body failed validation."):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON body; a missing/unparseable body behaves as an empty object."""
    raw = request.get_json(silent=True)
    if raw is None:
        if request.data:
            # a body was sent but is not valid JSON
            raise bad_request("Request body is not valid JSON.")
        return {}
    if not isinstance(raw, dict):
        raise bad_request("Request body must be a JSON object.")
    return raw


def parse_datetime(value, field):
    if not isinstance(value, str):
        raise bad_request("%s must be an ISO 8601 UTC timestamp string." % field)
    match = _DT_RE.match(value.strip())
    if not match:
        raise bad_request("%s is not a well-formed ISO 8601 UTC timestamp." % field)
    year, month, day, hour, minute = (int(match.group(i)) for i in range(1, 6))
    second = int(match.group(6) or 0)
    frac = match.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        raise bad_request("%s is not a valid calendar timestamp." % field)
    if match.group(9):
        sign = -1 if match.group(9) == "+" else 1
        offset = timedelta(hours=int(match.group(10)), minutes=int(match.group(11)))
        dt = dt + sign * offset
    return dt


def _present(data, field):
    return field in data and data[field] is not None


def req_string(data, field, allow_blank=False):
    if not _present(data, field):
        raise bad_request("%s is required." % field)
    value = data[field]
    if not isinstance(value, str):
        raise bad_request("%s must be a string." % field)
    if not allow_blank and not value.strip():
        raise bad_request("%s must not be blank." % field)
    return value


def opt_string(data, field, default=None, allow_blank=True):
    if not _present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        raise bad_request("%s must be a string." % field)
    if not allow_blank and not value.strip():
        raise bad_request("%s must not be blank." % field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    if not _present(data, field):
        raise bad_request("%s is required." % field)
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not _present(data, field):
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be <= %s." % (field, maximum))
    return value


def req_number(data, field, minimum=None, maximum=None):
    if not _present(data, field):
        raise bad_request("%s is required." % field)
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be a number." % field)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be <= %s." % (field, maximum))
    return value


def req_bool(data, field):
    if not _present(data, field):
        raise bad_request("%s is required." % field)
    if not isinstance(data[field], bool):
        raise bad_request("%s must be a boolean." % field)
    return data[field]


def opt_bool(data, field, default=None):
    if not _present(data, field):
        return default
    if not isinstance(data[field], bool):
        raise bad_request("%s must be a boolean." % field)
    return data[field]


def req_enum(data, field, choices):
    value = req_string(data, field)
    if value not in choices:
        raise bad_request("%s must be one of %s." % (field, ", ".join(choices)))
    return value


def opt_enum(data, field, choices, default=None):
    if not _present(data, field):
        return default
    value = req_string(data, field)
    if value not in choices:
        raise bad_request("%s must be one of %s." % (field, ", ".join(choices)))
    return value


def req_dt(data, field):
    if not _present(data, field):
        raise bad_request("%s is required." % field)
    return parse_datetime(data[field], field)


def opt_dt(data, field, default=None):
    if not _present(data, field):
        return default
    return parse_datetime(data[field], field)


def req_list(data, field, allow_empty=True):
    if not _present(data, field):
        raise bad_request("%s is required." % field)
    value = data[field]
    if not isinstance(value, list):
        raise bad_request("%s must be an array." % field)
    if not allow_empty and not value:
        raise bad_request("%s must not be empty." % field)
    return value


def req_object(data, field):
    if not _present(data, field):
        raise bad_request("%s is required." % field)
    value = data[field]
    if not isinstance(value, dict):
        raise bad_request("%s must be an object." % field)
    return value


def opt_object(data, field, default=None):
    if not _present(data, field):
        return default
    value = data[field]
    if not isinstance(value, dict):
        raise bad_request("%s must be an object." % field)
    return value


def req_id_list(data, field):
    value = req_list(data, field)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise bad_request("%s must contain identifier strings." % field)
    return value


# ------------------------------------------------------------------ pagination
def pagination():
    limit = _page_param("limit", config.PAGE_LIMIT_DEFAULT,
                        config.PAGE_LIMIT_MIN, config.PAGE_LIMIT_MAX)
    offset = _page_param("offset", config.PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def _page_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        raise ApiError("ERR_PAGINATION_INVALID", "%s must be an integer." % name)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError("ERR_PAGINATION_INVALID", "%s is out of the permitted range." % name)
    return value
