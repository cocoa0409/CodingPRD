"""Shared validation helpers and precision utilities.

Precision rules per PRD §2.5:
  - fiber weights: 0.01 lb
  - costs: 0.0001 USD
  - shrinkage / count-deviation / yardage-deviation / yardage aggregates: 0.01
  - delta-E: 0.001
All rounding is ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import err_invalid_request


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def dec(value):
    """Convert a JSON numeric (int/float/str) to Decimal. Raises on bad input."""
    if isinstance(value, bool):
        raise ValueError("boolean is not numeric")
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise ValueError("not numeric")
    raise ValueError("not numeric")


def round_q(value, places):
    """Round a Decimal to `places` decimal places using ROUND_HALF_UP."""
    q = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(q, rounding=ROUND_HALF_UP)


def round2(value):
    return round_q(value, 2)


def round3(value):
    return round_q(value, 3)


def round4(value):
    return round_q(value, 4)


def to_number(d):
    """Serialize a Decimal as an int when integral, else a float."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------

def get_json_body():
    """Return the JSON request body as a dict; raise ERR_INVALID_REQUEST otherwise."""
    if not request.is_json:
        raise err_invalid_request("Request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def _require_field(body, name):
    if name not in body or body[name] is None:
        raise err_invalid_request(f"Missing required field: {name}")
    return body[name]


def req_string(body, name):
    v = _require_field(body, name)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request(f"Field {name} must be a non-empty string")
    return v


def req_decimal(body, name, min_value=None, max_value=None, min_exclusive=False, max_exclusive=False):
    raw = _require_field(body, name)
    try:
        v = dec(raw)
    except ValueError:
        raise err_invalid_request(f"Field {name} must be numeric")
    if min_value is not None:
        if min_exclusive and v <= Decimal(str(min_value)):
            raise err_invalid_request(f"Field {name} must be > {min_value}")
        if not min_exclusive and v < Decimal(str(min_value)):
            raise err_invalid_request(f"Field {name} must be >= {min_value}")
    if max_value is not None:
        if max_exclusive and v >= Decimal(str(max_value)):
            raise err_invalid_request(f"Field {name} must be < {max_value}")
        if not max_exclusive and v > Decimal(str(max_value)):
            raise err_invalid_request(f"Field {name} must be <= {max_value}")
    return v


def opt_decimal(body, name, min_value=None, max_value=None, min_exclusive=False, max_exclusive=False, default=None):
    if name not in body or body[name] is None:
        return default
    return req_decimal(body, name, min_value, max_value, min_exclusive, max_exclusive)


def req_int(body, name, min_value=None, max_value=None):
    raw = _require_field(body, name)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise err_invalid_request(f"Field {name} must be an integer")
    if min_value is not None and raw < min_value:
        raise err_invalid_request(f"Field {name} must be >= {min_value}")
    if max_value is not None and raw > max_value:
        raise err_invalid_request(f"Field {name} must be <= {max_value}")
    return raw


def req_enum(body, name, allowed):
    v = _require_field(body, name)
    if v not in allowed:
        raise err_invalid_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Pagination (limit/offset per scaffold response_envelope.pagination_defaults)
# ---------------------------------------------------------------------------

def get_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except ValueError:
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except ValueError:
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def apply_filters(items, filters):
    """Apply equality filters. `filters` is a dict of field -> raw query value."""
    out = list(items)
    for field, raw in filters.items():
        if raw is None:
            continue
        out = [it for it in out if _matches(it.get(field), raw)]
    return out


def _matches(value, raw):
    if isinstance(value, bool):
        return raw.lower() in ("true", "1", "yes") == value
    if value is None:
        return raw in ("null", "")
    return str(value) == raw


def sort_and_paginate(items, limit, offset):
    """Sort by created_at ascending, then apply offset/limit. Returns (page, total)."""
    ordered = sorted(items, key=lambda it: (it.get("created_at") or "", it.get("id") or ""))
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return page, total
