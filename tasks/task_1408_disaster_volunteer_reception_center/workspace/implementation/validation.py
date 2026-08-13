"""Request body shape validation (pipeline stage 4) and common primitives."""

from datetime import timezone
from decimal import Decimal

from flask import request

import db
from errors import ERR_INVALID_REQUEST, raise_error

SKILL_CODES = ["GENERAL_LABOR", "CHAINSAW", "MEDICAL", "CDL", "SHELTER_OPS", "TRANSLATION"]
CREDENTIAL_CLASSES = ["STANDARD", "ADVANCED"]
PPE_ITEM_TYPES = ["GLOVES", "MASK", "HARD_HAT", "VEST", "GOGGLES"]
HAZARD_LEVELS = ["GREEN", "AMBER", "RED"]
CRITICALITIES = ["STANDARD", "CRITICAL"]
CLEARANCE_TYPES = ["SAFETY_BRIEFING", "LIABILITY_WAIVER"]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RISK_CATEGORIES = ["SAFETY_VIOLATION", "MISCONDUCT", "NO_SHOW_PATTERN", "OTHER"]
PPE_OUTCOMES = ["RETURNED", "DAMAGED", "LOST"]


def get_body():
    """Return the JSON request body as a dict; anything else is a shape error."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def _invalid(message):
    raise_error(ERR_INVALID_REQUEST, message)


def check_unknown_fields(body, allowed):
    for key in body:
        if key not in allowed:
            _invalid(f"Unknown payload field: {key}")


def req_string(body, field):
    value = body.get(field)
    if value is None:
        _invalid(f"Missing required field: {field}")
    if not isinstance(value, str) or value == "":
        _invalid(f"Field {field} must be a non-empty string")
    return value


def opt_string(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        _invalid(f"Field {field} must be a string")
    return value


def req_int(body, field, minimum=None):
    value = body.get(field)
    if value is None:
        _invalid(f"Missing required field: {field}")
    if isinstance(value, bool) or not isinstance(value, int):
        _invalid(f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        _invalid(f"Field {field} must be at least {minimum}")
    return value


def req_enum(body, field, members):
    value = body.get(field)
    if value is None:
        _invalid(f"Missing required field: {field}")
    if value not in members:
        _invalid(f"Field {field} must be one of {members}")
    return value


def opt_enum(body, field, members):
    value = body.get(field)
    if value is None:
        return None
    if value not in members:
        _invalid(f"Field {field} must be one of {members}")
    return value


def req_datetime(body, field):
    value = body.get(field)
    if value is None:
        _invalid(f"Missing required field: {field}")
    parsed = db.parse_ts(value)
    if parsed is None:
        _invalid(f"Field {field} must be a valid ISO 8601 UTC timestamp")
    return parsed


def opt_datetime(body, field):
    if field not in body or body.get(field) is None:
        return None
    parsed = db.parse_ts(body.get(field))
    if parsed is None:
        _invalid(f"Field {field} must be a valid ISO 8601 UTC timestamp")
    return parsed


def req_hours(body, field="hours"):
    """Hours shape rules: 0 < hours <= 16 and a multiple of 0.25."""
    value = body.get(field)
    if value is None:
        _invalid(f"Missing required field: {field}")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid(f"Field {field} must be a number")
    dec = Decimal(str(value))
    if dec <= 0 or dec > 16:
        _invalid("hours must be positive and at most 16")
    if (dec * 4) % 1 != 0:
        _invalid("hours must be a multiple of 0.25")
    return dec


def req_ppe_stock(body, field="ppe_stock"):
    value = body.get(field)
    if value is None:
        _invalid(f"Missing required field: {field}")
    if not isinstance(value, dict):
        _invalid("ppe_stock must be an object")
    if set(value.keys()) != set(PPE_ITEM_TYPES):
        _invalid(f"ppe_stock must carry exactly the keys {PPE_ITEM_TYPES}")
    stock = {}
    for key, qty in value.items():
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            _invalid(f"ppe_stock[{key}] must be a non-negative integer")
        stock[key] = qty
    return stock


def check_hours_within_shift(hours_dec, shift):
    """Creation-shape rule tying hours to the shift's duration."""
    if hours_dec > Decimal(str(shift["duration_hours"])):
        _invalid("hours may not exceed the assignment shift's duration_hours")


def utc_date_of(dt):
    return dt.astimezone(timezone.utc).date()
