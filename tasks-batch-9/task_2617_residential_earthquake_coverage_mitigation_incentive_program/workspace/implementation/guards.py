"""The validation ladder of PRD section 2.8, rung by rung.

Every helper here corresponds to one rung.  Route handlers call them in
ascending rung order and return the first violation, so the lowest rung always
wins and no later rung is ever evaluated.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError

# --- rung 1: the seven declared roles (PRD 2.1) --------------------------
ROLES = (
    "ProgramAdmin",
    "ParticipatingInsurer",
    "Policyholder",
    "GrantReviewer",
    "FieldInspector",
    "ClaimAdjuster",
    "CertifiedContractor",
)

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


def acting_id():
    value = request.headers.get(USER_HEADER)
    return value.strip() if isinstance(value, str) else None


def auth(allowed_roles, need_user_id=False):
    """Rungs 1-3.

    Rung 1: X-User-Role present and one of the seven roles, else ERR_MISSING_ROLE.
    Rung 2: the role must be authorised for the endpoint, else ERR_UNAUTHORIZED.
    Rung 3: X-User-ID present and non-empty on the five duty-segregated
            operations, else ERR_MISSING_USER_ID.
    """
    role = request.headers.get(ROLE_HEADER)
    if role is None or role not in ROLES:
        raise ApiError("ERR_MISSING_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    if need_user_id:
        user = acting_id()
        if not user:
            raise ApiError("ERR_MISSING_USER_ID")
    return role


# --- rungs 4-5: existence -------------------------------------------------
NOT_FOUND = {
    "policyholders": "ERR_POLICYHOLDER_NOT_FOUND",
    "insurers": "ERR_INSURER_NOT_FOUND",
    "dwellings": "ERR_DWELLING_NOT_FOUND",
    "offers": "ERR_OFFER_NOT_FOUND",
    "policies": "ERR_POLICY_NOT_FOUND",
    "cycles": "ERR_GRANT_CYCLE_NOT_FOUND",
    "grants": "ERR_GRANT_NOT_FOUND",
    "contractors": "ERR_CONTRACTOR_NOT_FOUND",
    "projects": "ERR_PROJECT_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "events": "ERR_EVENT_NOT_FOUND",
    "layers": "ERR_LAYER_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "allocations": "ERR_ALLOCATION_NOT_FOUND",
}

# Rung 5 evaluates body foreign keys in the order PRD 2.4/2.8 lists them.
FK_ORDER = (
    ("insurer_id", "insurers"),
    ("policyholder_id", "policyholders"),
    ("dwelling_id", "dwellings"),
    ("policy_id", "policies"),
    ("accepted_offer_id", "offers"),
    ("grant_cycle_id", "cycles"),
    ("grant_id", "grants"),
    ("contractor_id", "contractors"),
    ("project_id", "projects"),
    ("event_id", "events"),
)


def path_row(collection, row_id):
    """Rung 4: a path identifier must resolve, else that kind's 404."""
    row = store.DB[collection].get(row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


def body_fks(body, fields):
    """Rung 5: every supplied body foreign key must resolve to an existing row.

    A field that is absent or null is not a resolution failure; its absence is
    caught later by rung 10 when the field is required.
    """
    resolved = {}
    for field, collection in FK_ORDER:
        if field not in fields:
            continue
        value = body.get(field)
        if value is None:
            resolved[field] = None
            continue
        if not isinstance(value, str) or value not in store.DB[collection]:
            raise ApiError(NOT_FOUND[collection])
        resolved[field] = store.DB[collection][value]
    return resolved


# --- rung 6: ownership ----------------------------------------------------

def owner_must_be(expected_id):
    """Rung 6: ERR_NOT_RESOURCE_OWNER when the acting identity is not the owner."""
    if acting_id() != expected_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --- rungs 7-9: segregation of duties ------------------------------------

def sod(recorded_handle, error_id):
    """The acting operator handle must differ from the recorded one."""
    if recorded_handle is not None and acting_id() == recorded_handle:
        raise ApiError(error_id)


# --- rung 10: request shape ----------------------------------------------

def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST")
    return payload


def required(payload, fields):
    """Rung 10: every required body field present and not null."""
    for field in fields:
        if field not in payload or payload[field] is None:
            raise ApiError("ERR_INVALID_REQUEST")


def required_string(payload, field):
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST")
    return value


# --- rung 11: enum domains ----------------------------------------------
ENUMS = {
    "county_hazard_tier": ("TIER_1", "TIER_2", "TIER_3"),
    "soil_class": ("ROCK", "STIFF", "SOFT", "LIQUEFACTION"),
    "structure_type": ("WOOD_FRAME_SLAB", "WOOD_FRAME_CRIPPLE_WALL", "MASONRY_URM", "MOBILE_HOME"),
    "deductible_pct": (5, 10, 15, 20, 25),
    "income_tier": ("TIER_LOW", "TIER_MID", "TIER_ANY"),
    "scope": ("CRIPPLE_WALL_BRACING", "EARTHQUAKE_BRACING_SYSTEM", "ANCHOR_BOLT_ONLY"),
    "decision": ("APPROVE", "RETURN", "DENY"),
    "result": ("PASS", "PARTIAL", "FAIL"),
    "lifecycle_action": ("LAPSE", "EXPIRE_QUOTE"),
    "compliance_action": ("SANCTION", "REINSTATE", "WITHDRAW"),
    "certification_status": ("CERTIFIED", "SUSPENDED"),
    "offer_response": ("ACCEPT", "DECLINE"),
    "layer_status": ("ACTIVE", "LAPSED"),
}


def enum(payload, field, domain_key, optional=False):
    """Rung 11: an enum-typed field must carry a value from its domain."""
    if field not in payload or payload[field] is None:
        if optional:
            return None
        raise ApiError("ERR_INVALID_REQUEST")
    value = payload[field]
    domain = ENUMS[domain_key]
    if domain_key == "deductible_pct":
        if isinstance(value, bool) or not isinstance(value, int) or value not in domain:
            raise ApiError("ERR_INVALID_ENUM_VALUE")
        return value
    if not isinstance(value, str) or value not in domain:
        raise ApiError("ERR_INVALID_ENUM_VALUE")
    return value


def enum_list(payload, field, domain_key):
    """Rung 11 over the members of a list-typed enum field."""
    value = payload.get(field)
    if not isinstance(value, list) or not value:
        raise ApiError("ERR_INVALID_REQUEST")
    domain = ENUMS[domain_key]
    for member in value:
        if not isinstance(member, str) or member not in domain:
            raise ApiError("ERR_INVALID_ENUM_VALUE")
    return list(value)


# --- rung 12: numeric domains -------------------------------------------

def integer(payload, field, minimum=None, maximum=None, exclusive_min=None):
    """Rung 12: an integer field inside its declared range, else ERR_INVALID_AMOUNT."""
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_AMOUNT")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_AMOUNT")
    if exclusive_min is not None and value <= exclusive_min:
        raise ApiError("ERR_INVALID_AMOUNT")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_AMOUNT")
    return value


def decimal_field(payload, field, minimum=None, maximum=None,
                  max_places=None, exclusive_min=None):
    """Rung 12 for a decimal multiplier / percentage."""
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ApiError("ERR_INVALID_AMOUNT")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ApiError("ERR_INVALID_AMOUNT")
    if not number.is_finite():
        raise ApiError("ERR_INVALID_AMOUNT")
    if minimum is not None and number < Decimal(str(minimum)):
        raise ApiError("ERR_INVALID_AMOUNT")
    if exclusive_min is not None and number <= Decimal(str(exclusive_min)):
        raise ApiError("ERR_INVALID_AMOUNT")
    if maximum is not None and number > Decimal(str(maximum)):
        raise ApiError("ERR_INVALID_AMOUNT")
    if max_places is not None:
        exponent = number.as_tuple().exponent
        if not isinstance(exponent, int) or exponent < -max_places:
            raise ApiError("ERR_INVALID_AMOUNT")
    return number


def instant(payload, field, optional=False):
    """A required timestamp field parsed into a datetime."""
    if field not in payload or payload[field] is None:
        if optional:
            return None
        raise ApiError("ERR_INVALID_REQUEST")
    parsed = store.parse_dt(payload[field])
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return parsed


def window(start, end):
    """Rung 13: every declared interval must be non-empty."""
    if start is None or end is None or not (start < end):
        raise ApiError("ERR_INVALID_WINDOW")


# --- rungs 14-15: optimistic concurrency --------------------------------

def occ(payload, field, current_version, error_id):
    """The pinned version must equal the ledger's current version."""
    pinned = payload.get(field)
    if isinstance(pinned, bool) or not isinstance(pinned, int) or pinned != current_version:
        raise ApiError(error_id)
    return pinned


# --- list filters (PRD 2.11: conjunctive, all optional) ------------------

def filtered(rows, spec):
    """Apply the optional query filters conjunctively."""
    for param, field in spec:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        rows = [row for row in rows if _matches(row.get(field), raw)]
    return rows


def _matches(stored, raw):
    if stored is None:
        return False
    if isinstance(stored, bool):
        return str(stored).lower() == str(raw).strip().lower()
    return str(stored) == str(raw).strip()


def unique_violation(collection, field, value, exclude_id=None):
    """Declared uniqueness constraints (naic_code, email, license_no, event_code).

    The catalogue names no dedicated error id for these, so a collision is a
    malformed request: ERR_INVALID_REQUEST.
    """
    for row in store.DB[collection].values():
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        if row.get(field) == value:
            raise ApiError("ERR_INVALID_REQUEST")


def optional_string(payload, field, default=""):
    value = payload.get(field)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST")
    return value


def optional_bool(payload, field, default=False):
    value = payload.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST")
    return value
