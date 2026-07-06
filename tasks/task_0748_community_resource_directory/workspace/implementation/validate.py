"""Shared input-shape validation helpers used across routes."""
from errors import ERR_INVALID_REQUEST, raise_error


CATEGORY_ENUM = {"FOOD", "HOUSING", "HEALTHCARE", "MENTAL_HEALTH", "EMPLOYMENT",
                 "TRANSPORT", "LEGAL_AID", "CHILDCARE"}
LANG_ENUM = {"EN", "ES", "FR", "ZH", "VI", "AR"}
ACCESS_ENUM = {"WHEELCHAIR", "HEARING_LOOP", "ASL_INTERPRETER", "LARGE_PRINT"}
URGENCY_ENUM = {"ROUTINE", "PRIORITY", "EMERGENCY"}
SCOPE_ENUM = {"BASIC_CONTACT", "FULL_CASE_FILE", "HEALTHCARE_HIPAA"}
TRANSPORT_MODE_ENUM = {"PUBLIC_TRANSIT", "CAR", "WALKING", "AGENCY_SHUTTLE"}
TRANSPORT_PLAN_MODE_ENUM = {"AGENCY_SHUTTLE", "RIDESHARE_VOUCHER"}
CURRENCY_ENUM = {"USD", "CAD", "EUR"}
ROUNDING_VARIANT_ENUM = {"PER_REFERRAL_ROUND_THEN_SUM", "SUM_THEN_ROUND"}
OUTCOME_ENUM = {"FULLY_MET", "PARTIALLY_MET", "UNMET"}


def require_body(body) -> dict:
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "body must be a JSON object")
    return body


def require_field(body: dict, field: str, kind=None):
    if field not in body:
        raise_error(ERR_INVALID_REQUEST, f"missing field: {field}")
    v = body[field]
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must not be null")
    if kind is not None and not isinstance(v, kind):
        raise_error(ERR_INVALID_REQUEST, f"field {field} has wrong type")
    return v


def require_str(body: dict, field: str) -> str:
    v = require_field(body, field)
    if not isinstance(v, str) or not v:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a non-empty string")
    return v


def require_int(body: dict, field: str) -> int:
    v = require_field(body, field)
    # bool is a subclass of int in python — exclude explicitly
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an integer")
    return v


def require_number(body: dict, field: str) -> float:
    v = require_field(body, field)
    if isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a number")
    if not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a number")
    return float(v)


def require_bool(body: dict, field: str) -> bool:
    v = require_field(body, field)
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a boolean")
    return v


def require_enum(body: dict, field: str, enum: set) -> str:
    v = require_str(body, field)
    if v not in enum:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be one of {sorted(enum)}")
    return v


def require_array(body: dict, field: str) -> list:
    v = require_field(body, field)
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an array")
    return v


def require_enum_subset(body: dict, field: str, enum: set, non_empty: bool = False) -> list:
    arr = require_array(body, field)
    for item in arr:
        if not isinstance(item, str) or item not in enum:
            raise_error(ERR_INVALID_REQUEST, f"field {field} contains invalid value")
    if non_empty and not arr:
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be non-empty")
    return arr


def parse_pagination(req_args) -> tuple[int, int]:
    """Read limit/offset from query args; enforce bounds. Return (limit, offset)."""
    limit_raw = req_args.get("limit")
    offset_raw = req_args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit must be in [1, 100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
