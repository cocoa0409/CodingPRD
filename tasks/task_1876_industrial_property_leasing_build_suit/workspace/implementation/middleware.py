"""Auth, request-body parsing, and field validation helpers.

Validation order follows PRD §2.8: authentication (401) -> role authorization
(403) -> representative ownership (403) -> existence (404) -> request shape
(400) -> enum membership (400) -> range sanity (422) -> state (409) -> OCC
(412) -> site gates (409) -> compliance gates (409) -> business batteries.
"""
import json
from decimal import Decimal

from flask import request

from errors import (
    ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INVALID_ENUM, not_found,
)
from timeutil import parse_iso

ROLES = {"TenantRep", "LeasingManager", "ProjectManager", "AssetManager", "ComplianceOfficer"}
ALL_ROLES = sorted(ROLES)


def authenticate(allowed_roles):
    """Priority 1-2: headers present + declared role, then role authorized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "Missing or invalid X-User-ID / X-User-Role headers", 401)
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN,
                       f"Role {role} is not authorized for this endpoint", 403)
    return user_id, role


def body():
    """Parse the JSON request body. Absent body -> {}. Decimals preserved."""
    raw = request.get_data(as_text=True)
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "Malformed JSON request body", 400)
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "JSON request body must be an object", 400)
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _type_ok(value, kind):
    if kind == "string":
        return isinstance(value, str)
    if kind == "int":
        return is_int(value)
    if kind == "number":
        return is_number(value)
    if kind == "datetime":
        return isinstance(value, str) and parse_iso(value) is not None
    return False


def require_fields(b, spec):
    """Priority 5: required request fields present with correct types.

    spec: list of (name, kind, required). kind in
    {string, int, number, datetime}.
    """
    for name, kind, required in spec:
        present = name in b and b[name] is not None
        if not present:
            if required:
                raise ApiError(ERR_INVALID_REQUEST,
                               f"Missing required field: {name}", 400)
            continue
        if not _type_ok(b[name], kind):
            raise ApiError(ERR_INVALID_REQUEST,
                           f"Field {name} has the wrong type", 400)


def check_enums(b, spec):
    """Priority 6: enum fields carry a declared member (ERR_INVALID_ENUM)."""
    for name, members in spec:
        if name in b and b[name] is not None and b[name] not in members:
            raise ApiError(ERR_INVALID_ENUM,
                           f"Field {name} must be one of {sorted(members)}", 400)


def get_fk(b, name, bucket):
    """Priority 4: body FK existence. Only meaningful for string ids; other
    types fall through to the shape check (400). Returns None when absent."""
    value = b.get(name)
    if isinstance(value, str):
        ent = bucket.get(value)
        if ent is None:
            raise not_found(name)
        return ent
    return None


def get_path(bucket, rid, what="resource"):
    ent = bucket.get(rid)
    if ent is None:
        raise not_found(what)
    return ent


USE_TYPES = {"DISTRIBUTION", "MANUFACTURING", "COLD_STORAGE", "R_AND_D"}
PARCEL_TYPES = {"EXISTING", "LAND_BANK"}
ENV_PHASES = {"PHASE_I_COMPLETE", "PHASE_II_REQUIRED", "REMEDIATED"}
COMMISSION_BASES = {"GROSS_AGGREGATE", "NET_EFFECTIVE"}
PRICING_METHODS = {"YIELD_ON_COST", "MARKET_COMP"}
MILESTONE_TYPES = {"PERMITS", "SHELL", "TI", "SUBSTANTIAL_COMPLETION"}
REVIEW_TYPES = {"ENVIRONMENTAL", "ZONING_USE"}
OUTCOMES = {"CLEARED", "FLAGGED"}
