"""Request-body validation helpers (PRD §2.6 priority 18: request shape)."""

from flask import request

from db import parse_iso, parse_date
from errors import invalid_request, invalid_enum


def get_body():
    """Return the JSON request body as a dict; empty body -> {}.

    Malformed JSON or a non-object JSON value is a request-shape failure.
    """
    data = request.get_data()
    if not data or not data.strip():
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def check_unknown_fields(body, allowed):
    """Reject any body field not in the endpoint's declared input list."""
    for key in body:
        if key not in allowed:
            raise invalid_request(f"Unknown field: {key}")


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise invalid_request(f"{field} is required and must be a string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"{field} must be a string")
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"{field} is required and must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"{field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise invalid_request(f"{field} must be <= {max_v}")
    return v


def opt_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"{field} must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"{field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise invalid_request(f"{field} must be <= {max_v}")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be a string")
    if v not in values:
        raise invalid_enum(f"{field} must be one of {sorted(values)}")
    return v


def opt_enum(body, field, values):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in values:
        raise invalid_enum(f"{field} must be one of {sorted(values)}")
    return v


def req_datetime(body, field):
    """Required ISO 8601 datetime -> aware UTC datetime."""
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be an ISO 8601 datetime string")
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise invalid_request(f"{field} must be a valid ISO 8601 datetime")


def opt_datetime(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"{field} must be an ISO 8601 datetime string")
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise invalid_request(f"{field} must be a valid ISO 8601 datetime")


def req_date(body, field):
    """Required YYYY-MM-DD date -> datetime.date."""
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be a YYYY-MM-DD date string")
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        raise invalid_request(f"{field} must be a valid YYYY-MM-DD date")
