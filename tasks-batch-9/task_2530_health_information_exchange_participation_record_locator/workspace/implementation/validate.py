"""Schema validation helpers.  Every failure is ERR_INVALID_REQUEST (PRD 2.9 #6)."""
import json
import re

from flask import request

from db import parse_date, parse_iso
from errors import bad_request

_DIGITS = re.compile(r"^\d+$")


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        raise bad_request("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("Request body must be a JSON object.")
    return parsed


def _present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, min_len=1, max_len=None, non_blank=True):
    if not _present(payload, key):
        raise bad_request("%s is required." % key)
    value = payload[key]
    if not isinstance(value, str):
        raise bad_request("%s must be a string." % key)
    probe = value.strip() if non_blank else value
    if len(probe) < min_len:
        raise bad_request("%s is too short." % key)
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s is too long." % key)
    return value


def opt_str(payload, key, default=None, min_len=0, max_len=None):
    if not _present(payload, key):
        return default
    return req_str(payload, key, min_len=min_len, max_len=max_len, non_blank=False)


def req_enum(payload, key, domain):
    value = req_str(payload, key)
    if value not in domain:
        raise bad_request("%s is outside its declared domain." % key)
    return value


def opt_enum(payload, key, domain, default=None):
    if not _present(payload, key):
        return default
    return req_enum(payload, key, domain)


def req_bool(payload, key, default=None):
    if not _present(payload, key):
        if default is None and key not in payload:
            raise bad_request("%s is required." % key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean." % key)
    return value


def opt_bool(payload, key, default):
    if not _present(payload, key):
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean." % key)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        raise bad_request("%s is required." % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad_request("%s is below its declared minimum." % key)
    if maximum is not None and value > maximum:
        raise bad_request("%s is above its declared maximum." % key)
    return value


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if not _present(payload, key):
        return default
    return req_int(payload, key, minimum=minimum, maximum=maximum)


def req_num(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        raise bad_request("%s is required." % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad_request("%s must be a number." % key)
    if minimum is not None and value < minimum:
        raise bad_request("%s is below its declared minimum." % key)
    if maximum is not None and value > maximum:
        raise bad_request("%s is above its declared maximum." % key)
    return value


def req_dt(payload, key):
    """Returns (verbatim string, parsed datetime)."""
    value = req_str(payload, key)
    parsed = parse_iso(value)
    if parsed is None:
        raise bad_request("%s is not an ISO 8601 UTC timestamp." % key)
    return value, parsed


def opt_dt(payload, key):
    if not _present(payload, key):
        return None, None
    return req_dt(payload, key)


def req_date(payload, key):
    value = req_str(payload, key)
    if parse_date(value) is None:
        raise bad_request("%s is not a YYYY-MM-DD date." % key)
    return value


def opt_date(payload, key):
    if not _present(payload, key):
        return None
    return req_date(payload, key)


def opt_digits(payload, key, length):
    if not _present(payload, key):
        return None
    value = payload[key]
    if not isinstance(value, str):
        raise bad_request("%s must be a string." % key)
    if not _DIGITS.match(value) or len(value) != length:
        raise bad_request("%s must be exactly %d digits." % (key, length))
    return value


def req_enum_list(payload, key, domain, allow_empty=True, required=True):
    if not _present(payload, key):
        if required:
            raise bad_request("%s is required." % key)
        return []
    value = payload[key]
    if not isinstance(value, list):
        raise bad_request("%s must be an array." % key)
    for item in value:
        if not isinstance(item, str) or item not in domain:
            raise bad_request("%s contains a value outside its declared domain." % key)
    if not allow_empty and len(value) == 0:
        raise bad_request("%s must not be empty." % key)
    return value


def opt_enum_list(payload, key, domain, default=None):
    if not _present(payload, key):
        return list(default) if default is not None else []
    return req_enum_list(payload, key, domain, required=False)


def req_id(payload, key):
    return req_str(payload, key)


def opt_id(payload, key):
    if not _present(payload, key):
        return None
    return req_str(payload, key)


def before(start_dt, end_dt, message):
    """Any interval whose start is not strictly before its end is a schema fault."""
    if start_dt is not None and end_dt is not None and start_dt >= end_dt:
        raise bad_request(message)
