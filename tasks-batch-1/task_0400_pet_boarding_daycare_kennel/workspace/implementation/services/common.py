"""Shared helpers: common system fields, date parsing, validation primitives,
round-half-up money math.
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import errors
from db import new_id, now_iso


# --------------------------------------------------------------------------
# Common system fields (PRD §2.4)
# --------------------------------------------------------------------------
def stamp_create(entity, with_version=True):
    """Attach id + created_at (+ updated_at/version) at creation."""
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version by one on a mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# --------------------------------------------------------------------------
# Money: round half up to whole cents
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a numeric (possibly Decimal) to the nearest integer, half up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(x):
    return Decimal(str(x))


# --------------------------------------------------------------------------
# Date helpers (YYYY-MM-DD; business date drives all math)
# --------------------------------------------------------------------------
def parse_date(s):
    """Parse YYYY-MM-DD strictly; return a date or raise ERR_INVALID_REQUEST."""
    if not isinstance(s, str):
        raise errors.err_invalid_request("Date must be a YYYY-MM-DD string.")
    parts = s.split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise errors.err_invalid_request("Date must be in YYYY-MM-DD form.")
    if len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise errors.err_invalid_request("Date must be in YYYY-MM-DD form.")
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise errors.err_invalid_request("Date is not a valid calendar date.")


def days_between(later_str, earlier_str):
    """later - earlier in whole days."""
    return (parse_date(later_str) - parse_date(earlier_str)).days


def add_days(date_str, n):
    return (parse_date(date_str) + timedelta(days=n)).isoformat()


# --------------------------------------------------------------------------
# Request-body validation primitives
# --------------------------------------------------------------------------
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err_invalid_request(f"Missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise errors.err_invalid_request(f"Field {field} must be one of {sorted(allowed)}")


def get_body():
    from flask import request
    # Parse JSON regardless of the declared Content-Type (force=True), so a
    # client that omits the application/json header still has its body read.
    body = request.get_json(silent=True, force=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise errors.err_invalid_request("Request body must be a JSON object.")
    return body
