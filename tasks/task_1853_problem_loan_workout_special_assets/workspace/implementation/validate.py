"""Payload validation helpers (ERR_INVALID_REQUEST discipline, PRD §2.11)."""
from flask import request

from db import parse_iso
from errors import invalid_request

_MISSING = object()


def get_body():
    """JSON object body; absent body counts as {} (action endpoints)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def no_unknown(data, allowed):
    extra = [k for k in data.keys() if k not in allowed]
    if extra:
        raise invalid_request(f"Unknown field(s): {', '.join(sorted(extra))}")


def field(data, name, default=_MISSING):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if default is _MISSING:
            raise invalid_request(f"Missing required field: {name}")
        return default
    return value


def as_str(value, name):
    if not isinstance(value, str):
        raise invalid_request(f"Field {name} must be a string")
    return value


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid_request(f"Field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise invalid_request(f"Field {name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise invalid_request(f"Field {name} must be <= {maximum}")
    return value


def as_enum(value, name, options):
    if not isinstance(value, str) or value not in options:
        raise invalid_request(
            f"Field {name} must be one of: {', '.join(options)}"
        )
    return value


def as_datetime(value, name):
    """Return (raw_string, parsed_utc_datetime); invalid -> 400."""
    text = as_str(value, name)
    parsed = parse_iso(text)
    if parsed is None:
        raise invalid_request(f"Field {name} must be an ISO 8601 datetime")
    return text, parsed
