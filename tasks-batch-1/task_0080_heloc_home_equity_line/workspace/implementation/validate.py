"""Body-field validation helpers. Raise ERR_INVALID_REQUEST (422) on violation."""
from errors import err
from response import _meta  # noqa: F401  (kept for parity, not strictly needed)


def bad(msg):
    raise err("ERR_INVALID_REQUEST", msg)


def get_body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def req_int(body, key, *, minimum=None, maximum=None, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            bad(f"Missing required field: {key}")
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        bad(f"Field {key} must be an integer")
    if minimum is not None and val < minimum:
        bad(f"Field {key} must be >= {minimum}")
    if maximum is not None and val > maximum:
        bad(f"Field {key} must be <= {maximum}")
    return val


def req_str(body, key, *, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            bad(f"Missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, str) or val == "":
        bad(f"Field {key} must be a non-empty string")
    return val


def req_enum(body, key, allowed, *, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            bad(f"Missing required field: {key}")
        return default
    val = body[key]
    if val not in allowed:
        bad(f"Field {key} must be one of {sorted(allowed)}")
    return val


def req_datetime(body, key, *, required=True, default=None):
    from store import parse_iso
    if key not in body or body[key] is None:
        if required:
            bad(f"Missing required field: {key}")
        return default
    val = body[key]
    if not isinstance(val, str):
        bad(f"Field {key} must be an ISO 8601 string")
    try:
        parse_iso(val)
    except Exception:
        bad(f"Field {key} must be a valid ISO 8601 datetime")
    return val
