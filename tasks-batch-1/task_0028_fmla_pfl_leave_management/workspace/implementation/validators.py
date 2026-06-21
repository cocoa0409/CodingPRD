"""Input/body validation primitives — raise ERR_INVALID_REQUEST on malformed bodies."""
from datetime import datetime

import clock
from errors import APIError
import errors as E


def require_json(req):
    if not req.is_json:
        raise APIError(E.ERR_INVALID_REQUEST, "Body must be JSON.", 400)
    body = req.get_json(silent=True)
    if not isinstance(body, dict):
        raise APIError(E.ERR_INVALID_REQUEST, "Body must be a JSON object.", 400)
    return body


def require_field(body, field, expected_types):
    if field not in body or body[field] is None:
        raise APIError(E.ERR_INVALID_REQUEST, f"Missing required field {field!r}.", 400)
    val = body[field]
    if not isinstance(val, expected_types):
        raise APIError(E.ERR_INVALID_REQUEST,
                       f"Field {field!r} has invalid type.", 400)
    # Boolean is subclass of int; guard against that confusion when expecting integer/number.
    if isinstance(val, bool) and bool not in (expected_types if isinstance(expected_types, tuple) else (expected_types,)):
        raise APIError(E.ERR_INVALID_REQUEST, f"Field {field!r} has invalid type.", 400)
    return val


def optional_field(body, field, expected_types, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, expected_types):
        raise APIError(E.ERR_INVALID_REQUEST,
                       f"Field {field!r} has invalid type.", 400)
    if isinstance(val, bool) and bool not in (expected_types if isinstance(expected_types, tuple) else (expected_types,)):
        raise APIError(E.ERR_INVALID_REQUEST, f"Field {field!r} has invalid type.", 400)
    return val


def parse_dt_field(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise APIError(E.ERR_INVALID_REQUEST, f"Missing required field {field!r}.", 400)
        return None
    raw = body[field]
    if not isinstance(raw, str):
        raise APIError(E.ERR_INVALID_REQUEST, f"Field {field!r} must be an ISO 8601 string.", 400)
    try:
        return clock.parse_iso8601(raw)
    except ValueError:
        raise APIError(E.ERR_INVALID_REQUEST, f"Field {field!r} must be a valid ISO 8601 datetime.", 400)


def require_enum(body, field, allowed):
    val = require_field(body, field, str)
    if val not in allowed:
        raise APIError(E.ERR_INVALID_REQUEST,
                       f"Field {field!r} must be one of {sorted(allowed)}.", 400)
    return val


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise APIError(E.ERR_INVALID_REQUEST,
                       f"Field {field!r} must be one of {sorted(allowed)}.", 400)
    return val
