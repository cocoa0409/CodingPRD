"""Request body field parsing and shape validation (PRD §2.6 priority 6).

Every shape violation raises ERR_MALFORMED_FIELD (400): missing required field,
invalid enum member, integer below its minimum, max_weight_lbs < min_weight_lbs,
unparseable date/datetime, wrong JSON type.
"""

import re
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import parse_iso
from errors import malformed, not_found

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    """Return the JSON request body as a dict; {} when absent. Non-dict -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise malformed("Request body must be a JSON object")
    return data


def req(body, name):
    """Required field: must be present and not null."""
    if name not in body or body[name] is None:
        raise malformed(f"Missing required field: {name}")
    return body[name]


def opt(body, name):
    """Optional field: None when absent or null."""
    return body.get(name)


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise malformed(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise malformed(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise malformed(f"{name} must be <= {maximum}")
    return value


def as_num(value, name, minimum=None, exclusive_minimum=False):
    """A 2-decimal-capable numeric input -> Decimal. Accepts int/float, not bool/str."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise malformed(f"{name} must be a number")
    d = Decimal(str(value))
    if minimum is not None:
        if exclusive_minimum:
            if d <= Decimal(str(minimum)):
                raise malformed(f"{name} must be > {minimum}")
        elif d < Decimal(str(minimum)):
            raise malformed(f"{name} must be >= {minimum}")
    return d


def as_str(value, name):
    if not isinstance(value, str):
        raise malformed(f"{name} must be a string")
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise malformed(f"{name} must be one of {sorted(allowed)}")
    return value


def as_date(value, name):
    """A calendar-date field: strict YYYY-MM-DD."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise malformed(f"{name} must be an ISO date (YYYY-MM-DD)")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise malformed(f"{name} is not a valid calendar date")


def as_datetime(value, name):
    """An instant field: ISO 8601 with a time component."""
    if not isinstance(value, str) or "T" not in value:
        raise malformed(f"{name} must be an ISO 8601 datetime")
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        raise malformed(f"{name} is not a valid ISO 8601 datetime")


def load_or_404(store_dict, entity_id, what="Resource"):
    rec = store_dict.get(entity_id)
    if rec is None:
        raise not_found(f"{what} not found: {entity_id}")
    return rec


def round2(d):
    """Round half-up to exactly two decimal places (Decimal)."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_int(d):
    """Round half-up to a whole integer (Decimal in, int out)."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
