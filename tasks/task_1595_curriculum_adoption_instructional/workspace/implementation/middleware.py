"""Auth extraction, role checks, and request-body field validation.

Validation cascade (PRD §2.7):
  1  auth context headers      -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2  role admission/ownership  -> ERR_INSUFFICIENT_PERMISSIONS (403)
  3  existence (path L-to-R, then body FK ids) -> ERR_NOT_FOUND (404)
  4  request shape             -> ERR_VALIDATION (400)
  5  state                     -> ERR_INVALID_STATE family (409)
  6  OCC                       -> ERR_STALE_CYCLE_VERSION (412)
  7  temporal windows          -> 409
  8  interval occupation       -> 409
  9  safety (freeze/SoD)       -> ERR_MATERIAL_FROZEN 409 / ERR_SEGREGATION_OF_DUTIES 403
  10 domain thresholds         -> 409 family
  11 referential               -> 409 family
  12 fiscal envelope           -> ERR_BUDGET_ENVELOPE_EXCEEDED (402)
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import (insufficient_permissions, missing_context, not_found,
                    validation)

ROLES = (
    "DistrictAdmin",
    "CurriculumDirector",
    "InstructionalSpecialist",
    "BoardSecretary",
    "ProcurementOfficer",
    "WarehouseManager",
    "Teacher",
    "CommitteeMember",
    "CommunityMember",
)

ALL_ROLES = ROLES


def auth_context():
    """Cascade tier 1: both headers present, role one of the nine declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise missing_context()
    return user_id, role


def require_roles(role, allowed):
    """Cascade tier 2 (role part)."""
    if role not in allowed:
        raise insufficient_permissions()


# ---------------------------------------------------------------------------
# Body helpers (tier 4)
# ---------------------------------------------------------------------------


def get_body():
    """Return the JSON object body; `{}` when absent so required-field checks
    fire with ERR_VALIDATION; 400 when the body is not a JSON object."""
    data = request.get_json(silent=True, force=False)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise validation("request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise validation("missing or invalid required string field: %s" % field)
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise validation("field %s must be a string" % field)
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if v is None or not _is_int(v):
        raise validation("missing or invalid required integer field: %s" % field)
    if minimum is not None and v < minimum:
        raise validation("field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise validation("field %s must be <= %s" % (field, maximum))
    return v


def opt_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise validation("field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise validation("field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise validation("field %s must be <= %s" % (field, maximum))
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v not in allowed:
        raise validation("missing or invalid enum field: %s" % field)
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise validation("field %s must be one of %s" % (field, sorted(allowed)))
    return v


def req_decimal(data, field, minimum=None, exclusive_minimum=False):
    v = data.get(field)
    if v is None or not _is_number(v):
        raise validation("missing or invalid numeric field: %s" % field)
    d = _to_decimal(v, field)
    if minimum is not None:
        if exclusive_minimum and d <= minimum:
            raise validation("field %s must be > %s" % (field, minimum))
        if not exclusive_minimum and d < minimum:
            raise validation("field %s must be >= %s" % (field, minimum))
    return d


def opt_decimal(data, field, minimum=None, maximum=None, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not _is_number(v):
        raise validation("field %s must be a number" % field)
    d = _to_decimal(v, field)
    if minimum is not None and d < minimum:
        raise validation("field %s must be >= %s" % (field, minimum))
    if maximum is not None and d > maximum:
        raise validation("field %s must be <= %s" % (field, maximum))
    return d


def _to_decimal(v, field):
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise validation("field %s must be a number" % field)
    if d.is_nan() or d.is_infinite():
        raise validation("field %s must be a finite number" % field)
    return d


def req_iso_dt(data, field):
    from db import parse_dt
    v = data.get(field)
    if v is None:
        raise validation("missing required datetime field: %s" % field)
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise validation("field %s must be an ISO 8601 datetime" % field)


def req_iso_date(data, field):
    from db import parse_date
    v = data.get(field)
    if v is None:
        raise validation("missing required date field: %s" % field)
    try:
        return parse_date(v)
    except (ValueError, TypeError):
        raise validation("field %s must be an ISO date (YYYY-MM-DD)" % field)


# ---------------------------------------------------------------------------
# Existence helpers (tier 3)
# ---------------------------------------------------------------------------


def get_or_404(collection, entity_id, resource_type):
    entity = collection.get(entity_id) if isinstance(entity_id, str) else None
    if entity is None:
        raise not_found(resource_type)
    return entity
