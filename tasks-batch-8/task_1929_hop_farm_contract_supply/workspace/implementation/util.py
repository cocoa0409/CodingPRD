"""Request-body validation helpers (PRD §2.8 priority 4: request shape)."""

import math
from decimal import Decimal

from flask import request

from db import parse_iso
from errors import invalid_request


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
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be a string")
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


def _as_decimal(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"{field} must be a number")
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise invalid_request(f"{field} must be a finite number")
    return Decimal(str(v))


def req_num(body, field, gt=None, gte=None, lte=None):
    """Required JSON number; range checks are exact (Decimal). Returns the raw
    parsed value so caller-supplied precision is preserved on output."""
    v = body.get(field)
    d = _as_decimal(v, field)
    if gt is not None and not d > Decimal(str(gt)):
        raise invalid_request(f"{field} must be > {gt}")
    if gte is not None and not d >= Decimal(str(gte)):
        raise invalid_request(f"{field} must be >= {gte}")
    if lte is not None and not d <= Decimal(str(lte)):
        raise invalid_request(f"{field} must be <= {lte}")
    return v


def opt_num(body, field, gt=None, gte=None, lte=None):
    v = body.get(field)
    if v is None:
        return None
    d = _as_decimal(v, field)
    if gt is not None and not d > Decimal(str(gt)):
        raise invalid_request(f"{field} must be > {gt}")
    if gte is not None and not d >= Decimal(str(gte)):
        raise invalid_request(f"{field} must be >= {gte}")
    if lte is not None and not d <= Decimal(str(lte)):
        raise invalid_request(f"{field} must be <= {lte}")
    return v


def req_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str) or v not in values:
        raise invalid_request(f"{field} must be one of {', '.join(sorted(values))}")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be an ISO 8601 datetime string")
    try:
        return parse_iso(v)
    except (ValueError, OverflowError):
        raise invalid_request(f"{field} must be a well-formed ISO 8601 datetime")


def req_str_list(body, field, min_items=0):
    v = body.get(field)
    if not isinstance(v, list):
        raise invalid_request(f"{field} is required and must be an array")
    if len(v) < min_items:
        raise invalid_request(f"{field} must contain at least {min_items} item(s)")
    for item in v:
        if not isinstance(item, str):
            raise invalid_request(f"{field} entries must be strings")
    if len(set(v)) != len(v):
        raise invalid_request(f"{field} entries must be distinct")
    return v
