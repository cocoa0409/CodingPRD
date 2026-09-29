"""Request-shape validation helpers — every failure is ERR_INVALID_REQUEST (400)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import bad_request

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

MISSING = object()


def json_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise bad_request("request body is not valid JSON")
    if not isinstance(payload, dict):
        raise bad_request("request body must be a JSON object")
    return payload


def present(body, name):
    return name in body and body[name] is not None


def _require(body, name):
    if name not in body or body[name] is None:
        raise bad_request("%s is required" % name)
    return body[name]


# ------------------------------------------------------------------ strings

def req_str(body, name, pattern=None, min_len=1, max_len=None, upper=False):
    value = _require(body, name)
    if not isinstance(value, str):
        raise bad_request("%s must be a string" % name)
    if len(value) < min_len:
        raise bad_request("%s must not be empty" % name)
    if max_len is not None and len(value) > max_len:
        raise bad_request("%s must be at most %d characters" % (name, max_len))
    if upper and value != value.upper():
        raise bad_request("%s must be uppercase" % name)
    if pattern is not None and not re.match(pattern, value):
        raise bad_request("%s has an invalid format" % name)
    return value


def opt_str(body, name, default=None, pattern=None, max_len=None):
    if not present(body, name):
        return default
    return req_str(body, name, pattern=pattern, max_len=max_len)


def req_icao(body, name, length):
    value = _require(body, name)
    if not isinstance(value, str) or not re.match(r"^[A-Z]{%d}$" % length, value):
        raise bad_request("%s must be exactly %d uppercase letters" % (name, length))
    return value


def req_enum(body, name, allowed):
    value = _require(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


# ------------------------------------------------------------------ numbers

def _as_int(value, name):
    if isinstance(value, bool):
        raise bad_request("%s must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    raise bad_request("%s must be an integer" % name)


def req_int(body, name, minimum=None, maximum=None):
    value = _as_int(_require(body, name), name)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be at most %s" % (name, maximum))
    return value


def opt_int(body, name, default=0, minimum=None, maximum=None):
    if not present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def _as_num(value, name):
    if isinstance(value, bool):
        raise bad_request("%s must be a number" % name)
    if isinstance(value, (int, float)):
        return value
    raise bad_request("%s must be a number" % name)


def req_num(body, name, minimum=None, maximum=None, exclusive_min=None):
    value = _as_num(_require(body, name), name)
    if minimum is not None and value < minimum:
        raise bad_request("%s must be at least %s" % (name, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        raise bad_request("%s must be greater than %s" % (name, exclusive_min))
    if maximum is not None and value > maximum:
        raise bad_request("%s must be at most %s" % (name, maximum))
    return value


def opt_num(body, name, default=0, minimum=None, maximum=None):
    if not present(body, name):
        return default
    return req_num(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name):
    value = _require(body, name)
    if not isinstance(value, bool):
        raise bad_request("%s must be a boolean" % name)
    return value


def opt_bool(body, name, default=False):
    if not present(body, name):
        return default
    return req_bool(body, name)


# ------------------------------------------------------------------ temporal

def parse_datetime(value, name):
    if not isinstance(value, str) or not _ISO_RE.match(value):
        raise bad_request("%s must be an ISO 8601 datetime" % name)
    text = value.strip()
    text = text.replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    if len(text) >= 5 and (text[-5] in "+-") and ":" not in text[-5:]:
        text = text[:-2] + ":" + text[-2:]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("%s must be an ISO 8601 datetime" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(body, name):
    value = _require(body, name)
    return value, parse_datetime(value, name)


def opt_datetime(body, name):
    if not present(body, name):
        return None, None
    return req_datetime(body, name)


def parse_date(value, name):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise bad_request("%s must be a YYYY-MM-DD date" % name)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise bad_request("%s must be a YYYY-MM-DD date" % name)


def req_date(body, name):
    value = _require(body, name)
    return value, parse_date(value, name)


def opt_date(body, name):
    if not present(body, name):
        return None, None
    return req_date(body, name)


def req_month(body, name):
    value = _require(body, name)
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        raise bad_request("%s must be a YYYY-MM month" % name)
    return value


# ------------------------------------------------------------------ arrays

def req_str_list(body, name, non_empty=False):
    value = _require(body, name)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise bad_request("%s must be an array of strings" % name)
    if non_empty and len(value) == 0:
        raise bad_request("%s must not be empty" % name)
    return list(value)


def opt_str_list(body, name, default=None):
    if not present(body, name):
        return list(default) if default is not None else []
    return req_str_list(body, name)
