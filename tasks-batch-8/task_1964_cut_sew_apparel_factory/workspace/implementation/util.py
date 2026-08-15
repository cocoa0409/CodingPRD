"""Request-body parsing and field validators (PRD §2.6 step 4).

Bodies are parsed with parse_float=Decimal so yardage/wastage arithmetic is
exact (PRD §2.8). All validators raise ERR_INVALID_REQUEST on failure.
"""

import json
import re
from decimal import Decimal

from flask import request

from db import parse_date
from errors import invalid_request, not_found

ISO2_RE = re.compile(r"^[A-Z]{2}$")


def get_body():
    """Parse the JSON request body; an absent body is treated as {}.

    Per PRD the API never rejects unknown body fields (e.g. a body-supplied
    operator_id on piece-work entries is explicitly ignored per §3.6), so no
    unknown-field check is performed anywhere.
    """
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        body = json.loads(raw, parse_float=Decimal, parse_int=int)
    except Exception:
        raise invalid_request("request body must be valid JSON")
    if not isinstance(body, dict):
        raise invalid_request("request body must be a JSON object")
    return body


def req_field(body, name):
    if name not in body or body[name] is None:
        raise invalid_request(f"{name} is required")
    return body[name]


def opt_field(body, name):
    v = body.get(name)
    return None if v is None else v


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or v == "":
        raise invalid_request(f"{name} must be a non-empty string")
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"{name} must be a string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, name, min_v=None, max_v=None):
    v = req_field(body, name)
    if not _is_int(v):
        raise invalid_request(f"{name} must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"{name} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise invalid_request(f"{name} must be <= {max_v}")
    return v


def req_num(body, name, gt=None, ge=None, le=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        raise invalid_request(f"{name} must be a number")
    d = v if isinstance(v, Decimal) else Decimal(str(v))
    if gt is not None and not d > Decimal(str(gt)):
        raise invalid_request(f"{name} must be > {gt}")
    if ge is not None and not d >= Decimal(str(ge)):
        raise invalid_request(f"{name} must be >= {ge}")
    if le is not None and not d <= Decimal(str(le)):
        raise invalid_request(f"{name} must be <= {le}")
    return d


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise invalid_request(f"{name} must be a boolean")
    return v


def req_enum(body, name, values):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in values:
        raise invalid_request(f"{name} must be one of {sorted(values)}")
    return v


def req_list(body, name):
    v = req_field(body, name)
    if not isinstance(v, list):
        raise invalid_request(f"{name} must be an array")
    return v


def req_date(body, name):
    v = req_str(body, name)
    try:
        parse_date(v)
    except ValueError:
        raise invalid_request(f"{name} must be a valid ISO date (YYYY-MM-DD)")
    return v


def req_country(body, name):
    v = req_str(body, name)
    if not ISO2_RE.match(v):
        raise invalid_request(f"{name} must be an ISO 3166-1 alpha-2 code")
    return v


def fk_exists(body, field, table, label):
    """Body-FK existence (PRD §2.5, pipeline step 3 — runs before schema).

    Missing or non-string FK values are left for schema validation (step 4).
    """
    v = body.get(field)
    if isinstance(v, str) and v not in table:
        raise not_found(f"{label} {v} not found")


def validate_size_quantities(body, name="size_quantities"):
    """Shared schema for size_quantities arrays: [{size, qty}], qty > 0, no
    duplicate sizes, non-empty."""
    sq = req_list(body, name)
    if not sq:
        raise invalid_request(f"{name} must be a non-empty array")
    lines = []
    seen = set()
    for i, item in enumerate(sq):
        if not isinstance(item, dict):
            raise invalid_request(f"{name}[{i}] must be an object")
        size = item.get("size")
        qty = item.get("qty")
        if not isinstance(size, str) or not size:
            raise invalid_request(f"{name}[{i}].size must be a non-empty string")
        if not _is_int(qty) or qty <= 0:
            raise invalid_request(f"{name}[{i}].qty must be a positive integer")
        if size in seen:
            raise invalid_request(f"{name} contains duplicate size {size!r}")
        seen.add(size)
        lines.append({"size": size, "qty": qty})
    return lines
