"""Shared helpers: timestamps, ids, request body parsing, field validators,
pagination parameter handling."""

import uuid
from datetime import datetime, timedelta, timezone

from flask import request

from errors import ERR_INVALID_REQUEST, raise_error

# Monotonic wall-clock timestamp generator so created_at ordering is
# deterministic even for back-to-back requests within the same millisecond.
_last_dt = None


def fmt_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits; strictly
    increasing across calls."""
    global _last_dt
    dt = datetime.now(timezone.utc)
    if _last_dt is not None and dt <= _last_dt:
        dt = _last_dt + timedelta(milliseconds=1)
    _last_dt = dt
    return fmt_dt(dt)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def body():
    """JSON request body as a dict; empty/missing body becomes {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def v_str(data, key, required=True):
    value = data.get(key)
    if value is None:
        if required:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return None
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"Field {key} must be a string")
    return value


def v_int(data, key, required=True, minimum=None, maximum=None):
    value = data.get(key)
    if value is None:
        if required:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return None
    if not is_int(value):
        raise_error(ERR_INVALID_REQUEST, f"Field {key} must be an integer")
    if minimum is not None and value < minimum:
        raise_error(ERR_INVALID_REQUEST, f"Field {key} is below its minimum of {minimum}")
    if maximum is not None and value > maximum:
        raise_error(ERR_INVALID_REQUEST, f"Field {key} exceeds its maximum of {maximum}")
    return value


def v_num(data, key, required=True):
    value = data.get(key)
    if value is None:
        if required:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {key}")
        return None
    if not is_num(value):
        raise_error(ERR_INVALID_REQUEST, f"Field {key} must be a number")
    return value


def v_bool(data, key, default=False):
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise_error(ERR_INVALID_REQUEST, f"Field {key} must be a boolean")
    return value


def pagination_params():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""

    def parse(name, default):
        raw = request.args.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = parse("limit", 10)
    offset = parse("offset", 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None
