"""Auth, role checks, request-shape validation, pagination parsing.

Validation order per PRD §2.8 / scaffold §1.4:
auth headers (p1) -> role authorization (p2) -> path existence (p3) ->
request shape (p4) -> body FK references (p5) -> OCC (p6) ->
carrier-active gate (p7) -> from-state gate (p8) -> domain rules (p9+).
"""

from functools import wraps

from flask import request

import errors
from db import parse_dt
from envelope import err
from errors import ApiError

ROLES = {"CarrierAdmin", "ShipperComplianceOfficer", "Regulator"}

CATEGORIES = {
    "EXPLOSIVE", "FLAMMABLE_LIQUID", "OXIDIZER", "RADIOACTIVE",
    "INHALATION_TOXIC", "CORROSIVE", "MISC",
}

HAZARD_CLASSES = {
    "CLASS_1_1", "CLASS_1_2", "CLASS_1_3", "CLASS_2_1", "CLASS_2_2",
    "CLASS_2_3", "CLASS_3", "CLASS_4_1", "CLASS_4_2", "CLASS_4_3",
    "CLASS_5_1", "CLASS_5_2", "CLASS_6_1", "CLASS_6_2", "CLASS_7",
    "CLASS_8", "CLASS_9",
}

PACKING_GROUPS = {"PG_I", "PG_II", "PG_III", "PG_NONE"}
SPEC_PACKING_GROUPS = {"PG_I", "PG_II", "PG_III"}
PLACARD_TABLES = {"TABLE_1", "TABLE_2"}
SEGREGATION_GROUPS = {"SG_NONE", "SG_ACID", "SG_ALKALI", "SG_OXIDIZER", "SG_FLAMMABLE"}
VEHICLE_CLASSES = {"VAN", "FLATBED", "TANKER"}
TRAINING_TYPES = {"INITIAL", "RECURRENT"}
SEVERITIES = {"MINOR", "MAJOR", "CATASTROPHIC"}


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and the role declared",
        )
    return uid, role


def endpoint(allowed_roles):
    """Decorator: auth (p1) then role authorization (p2)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                uid, role = auth_context()
                if role not in allowed_roles:
                    raise ApiError(
                        errors.ERR_INSUFFICIENT_PERMISSIONS,
                        403,
                        "Role is not permitted for this endpoint",
                    )
                return fn(uid, role, *args, **kwargs)
            except ApiError as e:
                return err(e.error_id, e.message, e.status)

        return wrapper

    return deco


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid("Request body must be a JSON object")
    return data


def req(b, name):
    if name not in b or b[name] is None:
        raise errors.invalid(f"Missing required field: {name}")
    return b[name]


def opt(b, name, default=None):
    v = b.get(name, default)
    return default if v is None else v


def as_str(v, name):
    if not isinstance(v, str):
        raise errors.invalid(f"Field {name} must be a string")
    return v


def as_int(v, name):
    if type(v) is not int:
        raise errors.invalid(f"Field {name} must be an integer")
    return v


def as_num(v, name):
    if type(v) not in (int, float):
        raise errors.invalid(f"Field {name} must be a number")
    return v


def as_bool(v, name):
    if type(v) is not bool:
        raise errors.invalid(f"Field {name} must be a boolean")
    return v


def as_enum(v, name, members):
    if not isinstance(v, str) or v not in members:
        raise errors.invalid(f"Field {name} must be one of {sorted(members)}")
    return v


def as_enum_list(v, name, members):
    if not isinstance(v, list) or any(not isinstance(x, str) or x not in members for x in v):
        raise errors.invalid(f"Field {name} must be an array of declared enum members")
    return list(v)


def as_dt(v, name):
    dt = parse_dt(v)
    if dt is None:
        raise errors.invalid(f"Field {name} must be a valid ISO 8601 datetime")
    return dt


def pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise errors.invalid("limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise errors.invalid("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid("offset must be >= 0")
    return limit, offset


def get_or_404(table, entity_id, error_id, what):
    entity = table.get(entity_id)
    if entity is None:
        raise errors.not_found(error_id, what)
    return entity
