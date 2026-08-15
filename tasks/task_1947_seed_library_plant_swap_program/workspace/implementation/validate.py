"""Request-body shape validation helpers (band 4)."""

import math
from errors import invalid_request, invalid_enum
from db import parse_iso


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object.")
    return body


def req_string(body, field):
    v = body.get(field)
    if v is None:
        raise invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string.")
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"Field {field} must be a string.")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if v is None:
        raise invalid_request(f"Missing required field: {field}")
    if not _is_int(v):
        raise invalid_request(f"Field {field} must be an integer.")
    if min_v is not None and v < min_v:
        raise invalid_request(f"Field {field} must be >= {min_v}.")
    if max_v is not None and v > max_v:
        raise invalid_request(f"Field {field} must be <= {max_v}.")
    return v


def opt_int(body, field, min_v=None, max_v=None, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not _is_int(v):
        raise invalid_request(f"Field {field} must be an integer.")
    if min_v is not None and v < min_v:
        raise invalid_request(f"Field {field} must be >= {min_v}.")
    if max_v is not None and v > max_v:
        raise invalid_request(f"Field {field} must be <= {max_v}.")
    return v


def req_number(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if v is None:
        raise invalid_request(f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {field} must be a number.")
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise invalid_request(f"Field {field} must be finite.")
    if min_v is not None and v < min_v:
        raise invalid_request(f"Field {field} must be >= {min_v}.")
    if max_v is not None and v > max_v:
        raise invalid_request(f"Field {field} must be <= {max_v}.")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise invalid_request(f"Field {field} must be a boolean.")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        raise invalid_request(f"Missing required field: {field}")
    if not isinstance(v, str):
        raise invalid_enum(f"Field {field} must be one of {sorted(allowed)}.")
    if v not in allowed:
        raise invalid_enum(f"Field {field} value '{v}' not in declared set.")
    return v


def opt_enum(body, field, allowed, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise invalid_enum(f"Field {field} value '{v}' not in declared set.")
    return v


def req_zones(body, field):
    v = body.get(field)
    if v is None:
        raise invalid_request(f"Missing required field: {field}")
    if not isinstance(v, list) or len(v) == 0:
        raise invalid_request(f"Field {field} must be a non-empty array.")
    for z in v:
        if not isinstance(z, str):
            raise invalid_request(f"Field {field} entries must be strings.")
    return v


def opt_zones(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, list) or len(v) == 0:
        raise invalid_request(f"Field {field} must be a non-empty array.")
    for z in v:
        if not isinstance(z, str):
            raise invalid_request(f"Field {field} entries must be strings.")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if v is None:
        raise invalid_request(f"Missing required field: {field}")
    dt = parse_iso(v) if isinstance(v, str) else None
    if dt is None:
        raise invalid_request(f"Field {field} must be an ISO8601 datetime.")
    return dt


def opt_datetime(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    dt = parse_iso(v) if isinstance(v, str) else None
    if dt is None:
        raise invalid_request(f"Field {field} must be an ISO8601 datetime.")
    return dt


def parse_pagination():
    """Band-agnostic pagination parse: limit default 10 (min 1 max 100), offset default 0."""
    from flask import request
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100.")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer.")
        if offset < 0:
            raise invalid_request("offset must be >= 0.")
    return limit, offset
