"""Shared request-body validation helpers.

Per PRD §2.4: missing required field / type mismatch / out-of-range value ->
ERR_INVALID_REQUEST (400); enum violation -> ERR_INVALID_ENUM (400).
"""

import db
from errors import invalid_request, invalid_enum, not_found


def require_body(req_json):
    if req_json is None or not isinstance(req_json, dict):
        raise invalid_request("Request body must be a JSON object")
    return req_json


def require_field(body, name):
    if name not in body or body[name] is None:
        raise invalid_request(f"Missing required field: {name}")
    return body[name]


def optional_field(body, name, default=None):
    return body.get(name, default)


def require_string(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not v.strip():
        raise invalid_request(f"Field {name} must be a non-empty string")
    return v


def optional_string(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"Field {name} must be a string")
    return v


def require_int(body, name, minimum=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise invalid_request(f"Field {name} must be >= {minimum}")
    return v


def require_number(body, name):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request(f"Field {name} must be a number")
    return v


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise invalid_request(f"Field {name} must be a boolean")
    return v


def require_enum(body, name, allowed):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise invalid_enum(f"Field {name} must be a string enum value")
    if v not in allowed:
        raise invalid_enum(f"Field {name} must be one of {sorted(allowed)}")
    return v


def require_date(body, name):
    """Strict YYYY-MM-DD date; returns the date object. Caller stores the raw string."""
    raw = require_field(body, name)
    try:
        d = db.parse_iso_date(raw)
    except (ValueError, TypeError):
        raise invalid_request(f"Field {name} must be an ISO-8601 date (YYYY-MM-DD)")
    return raw, d


def require_datetime(body, name):
    raw = require_field(body, name)
    try:
        dt = db.parse_iso_datetime(raw)
    except (ValueError, TypeError):
        raise invalid_request(f"Field {name} must be an ISO-8601 UTC timestamp")
    return raw, dt


def get_or_404(store, entity_id, what):
    ent = store.get(entity_id)
    if ent is None:
        raise not_found(what)
    return ent


# Enum value sets (from SCAFFOLD §1.1)
ENUM_UNIT_KIND = {"REFRIGERATOR", "FREEZER"}
ENUM_PRESENTATION = {"SINGLE_DOSE_VIAL", "MULTI_DOSE_VIAL", "PRE_FILLED_SYRINGE"}
ENUM_STORAGE_REQUIREMENT = {
    "REFRIGERATED_2_8C",
    "FROZEN_MINUS_50_MINUS_15C",
    "ULTRA_COLD_MINUS_90_MINUS_60C",
}
ENUM_STOCK_TYPE = {"PUBLIC_VFC", "PRIVATE"}
ENUM_INSURANCE_CATEGORY = {
    "MEDICAID",
    "UNINSURED",
    "UNDERINSURED",
    "AMERICAN_INDIAN_ALASKA_NATIVE",
    "COMMERCIAL",
}
VFC_ELIGIBLE_CATEGORIES = {
    "MEDICAID",
    "UNINSURED",
    "UNDERINSURED",
    "AMERICAN_INDIAN_ALASKA_NATIVE",
}
ENUM_BORROW_DIRECTION = {"PUBLIC_FROM_PRIVATE", "PRIVATE_FROM_PUBLIC"}
ENUM_REASON_CODE = {"STOCK_OUT", "SHORT_DATE_AVOIDANCE", "EMERGENCY_CLINIC"}
