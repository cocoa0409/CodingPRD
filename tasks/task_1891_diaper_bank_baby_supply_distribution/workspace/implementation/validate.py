"""Request-body field validators and datetime parsing (pipeline category 10)."""

import re
from datetime import datetime, timezone

from db import SIZE_CODES
from errors import ERR_VALIDATION, raise_err


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, "%s must be an ISO 8601 datetime string." % field)
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_VALIDATION, "%s must be an ISO 8601 datetime string." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_PERIOD_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_period(value, field="period"):
    """Parse a 'YYYY-MM' calendar-month string -> (year, month)."""
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, "%s must be a 'YYYY-MM' string." % field)
    m = _PERIOD_RE.match(value.strip())
    if not m:
        raise_err(ERR_VALIDATION, "%s must be a 'YYYY-MM' string." % field)
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        raise_err(ERR_VALIDATION, "%s must be a valid calendar month." % field)
    return year, month


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_VALIDATION, "%s is required and must be a string." % field)
    return v


def opt_str(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, "%s must be a string." % field)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None):
    v = body.get(field)
    if not _is_int(v):
        raise_err(ERR_VALIDATION, "%s is required and must be an integer." % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_VALIDATION, "%s must be >= %d." % (field, minimum))
    return v


def opt_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not _is_int(v):
        raise_err(ERR_VALIDATION, "%s must be an integer." % field)
    if minimum is not None and v < minimum:
        raise_err(ERR_VALIDATION, "%s must be >= %d." % (field, minimum))
    return v


def opt_bool(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, "%s must be a boolean." % field)
    return v


def req_size_code(value, field="size_code"):
    if not isinstance(value, str) or value not in SIZE_CODES:
        raise_err(ERR_VALIDATION, "%s must be a known size code." % field)
    return value


def req_quantity_lines(body, field="lines"):
    """Array of {size_code, quantity>=1} used by intake batches and issuances."""
    lines = body.get(field)
    if not isinstance(lines, list) or len(lines) == 0:
        raise_err(ERR_VALIDATION, "%s must be a non-empty array." % field)
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise_err(ERR_VALIDATION, "Each entry of %s must be an object." % field)
        size = req_size_code(ln.get("size_code"))
        qty = ln.get("quantity")
        if not _is_int(qty) or qty < 1:
            raise_err(ERR_VALIDATION, "quantity must be an integer >= 1.")
        out.append({"size_code": size, "quantity": qty})
    return out


def req_po_lines(body, field="lines"):
    """Array of {size_code, quantity>=1, unit_cost_cents>=0} for purchase orders."""
    lines = body.get(field)
    if not isinstance(lines, list) or len(lines) == 0:
        raise_err(ERR_VALIDATION, "%s must be a non-empty array." % field)
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise_err(ERR_VALIDATION, "Each entry of %s must be an object." % field)
        size = req_size_code(ln.get("size_code"))
        qty = ln.get("quantity")
        if not _is_int(qty) or qty < 1:
            raise_err(ERR_VALIDATION, "quantity must be an integer >= 1.")
        cost = ln.get("unit_cost_cents")
        if not _is_int(cost) or cost < 0:
            raise_err(ERR_VALIDATION, "unit_cost_cents must be an integer >= 0.")
        out.append({"size_code": size, "quantity": qty, "unit_cost_cents": cost})
    return out


def req_children_sizes(body, field="children_sizes"):
    """1..8 SIZE_CODE entries (PRD §3.6)."""
    sizes = body.get(field)
    if not isinstance(sizes, list) or len(sizes) < 1 or len(sizes) > 8:
        raise_err(ERR_VALIDATION, "%s must contain between 1 and 8 entries." % field)
    for s in sizes:
        req_size_code(s, field)
    return list(sizes)
