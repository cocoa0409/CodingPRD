"""Auth middleware, body validators, and pagination parsing."""
import functools
import re
from datetime import date

from flask import g, request

from errors import ApiError, validation

ROLES = {
    "SystemAdmin",
    "LeaseAdmin",
    "FleetPlanner",
    "MaintenanceController",
    "BillingAnalyst",
    "ComplianceOfficer",
    "LesseeRep",
}

CREDIT_TIERS = {"TIER_A", "TIER_B", "TIER_C"}
CAR_TYPES = {"BOX", "COVERED_HOPPER", "GONDOLA", "FLAT", "TANK_GENERAL", "TANK_PRESSURE"}
COMMODITIES = {
    "GRAIN", "COAL", "PLASTIC_PELLETS", "CEMENT", "LUMBER",
    "CRUDE_OIL", "GASOLINE", "ETHANOL", "CORN_SYRUP", "CHEMICAL_SOLVENT",
}
LEASE_TYPES = {"FULL_SERVICE", "NET"}
RATE_KINDS = {"CAR_HIRE_BASE", "MILEAGE_CREDIT"}
DEFECT_CAUSES = {"WEAR_AND_TEAR", "LESSEE_DAMAGE", "PRE_EXISTING"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}
RETIRE_REASONS = {"AGE_LIMIT", "DAMAGE_BEYOND_REPAIR", "OBSOLESCENCE", "DIRECTIVE_ECONOMIC"}
CLEANING_GRADES = {"WASH", "STEAM_CLEAN"}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def require_roles(*roles):
    """Priority 1 (auth) then priority 2 (role membership)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED", 401,
                    "Missing or invalid X-User-ID / X-User-Role headers",
                )
            if role not in roles:
                raise ApiError(
                    "ERR_FORBIDDEN_ROLE", 403,
                    f"Role {role} is not permitted for this endpoint",
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def get_body():
    """Parse the JSON request body; a missing/malformed/non-object body is {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise validation("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def v_str(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise validation(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or v == "":
        raise validation(f"Field {name} must be a non-empty string")
    return v


def v_int(body, name, required=True, min=None, max=None):
    v = body.get(name)
    if v is None:
        if required:
            raise validation(f"Missing required field: {name}")
        return None
    if not _is_int(v):
        raise validation(f"Field {name} must be an integer")
    if min is not None and v < min:
        raise validation(f"Field {name} must be >= {min}")
    if max is not None and v > max:
        raise validation(f"Field {name} must be <= {max}")
    return v


def v_bool(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            raise validation(f"Missing required field: {name}")
        return default
    if not isinstance(v, bool):
        raise validation(f"Field {name} must be a boolean")
    return v


def v_enum(body, name, values, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise validation(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or v not in values:
        raise validation(f"Field {name} must be one of {sorted(values)}")
    return v


def v_date(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise validation(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise validation(f"Field {name} must be an ISO date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise validation(f"Field {name} must be a valid ISO date (YYYY-MM-DD)")


def v_month(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise validation(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or not _MONTH_RE.match(v):
        raise validation(f"Field {name} must be a month (YYYY-MM)")
    return v


def parse_pagination():
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("Query parameter limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("Query parameter offset must be an integer")
        if offset < 0:
            raise validation("Query parameter offset must be >= 0")
    return limit, offset
