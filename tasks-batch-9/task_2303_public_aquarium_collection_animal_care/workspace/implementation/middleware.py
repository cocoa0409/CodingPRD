"""Auth header extraction, RBAC, pagination and lookup helpers."""

from flask import request

import db
import response
import validators as V
from errors import ApiError

CURATOR = "CuratorOfCollections"
DIRECTOR = "ComplianceDirector"
VET = "VeterinaryOfficer"
AQUARIST = "AquaristTechnician"
PERMIT_OFFICER = "PermitOfficer"
LIAISON = "PartnerInstitutionLiaison"

ROLES = (CURATOR, DIRECTOR, VET, AQUARIST, PERMIT_OFFICER, LIAISON)
ANY_ROLE = set(ROLES)
NON_LIAISON = set(ROLES) - {LIAISON}

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    """Ladder ranks 1-3 (identity, role vocabulary, endpoint authorisation)."""
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    # Rank 1: identity only. An absent or empty X-User-ID is the missing-context
    # error; the role header is judged separately at rank 2.
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_MISSING_USER_CONTEXT")
    # Rank 2: an absent, empty or unrecognised role name is ERR_INVALID_ROLE.
    if role is None or role not in ANY_ROLE:
        raise ApiError("ERR_INVALID_ROLE")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def require_action_role(role, action, action_roles):
    """Ladder rank 3, action-level: only applied for recognised action values."""
    if action in action_roles and role not in action_roles[action]:
        raise ApiError("ERR_UNAUTHORIZED")


def json_body():
    return V.body_dict(request.get_json(silent=True))


# ---------------------------------------------------------------- lookups

_ENTITY_KEYS = {
    "life_support_systems": "LIFE_SUPPORT_SYSTEM",
    "exhibits": "EXHIBIT",
    "species": "SPECIES",
    "institutions": "INSTITUTION",
    "collection_plan_entries": "COLLECTION_PLAN_ENTRY",
    "acquisition_requests": "ACQUISITION_REQUEST",
    "permits": "PERMIT",
    "specimens": "SPECIMEN",
    "quarantine_cases": "QUARANTINE_CASE",
    "veterinary_cases": "VETERINARY_CASE",
    "transfer_requests": "TRANSFER_REQUEST",
    "interaction_sessions": "INTERACTION_SESSION",
    "accreditation_audits": "ACCREDITATION_AUDIT",
    "water_quality_readings": "WATER_QUALITY_READING",
    "husbandry_logs": "HUSBANDRY_LOG",
}


def fetch(collection, row_id):
    """Existence check (ranks 5 and 6). Raises ERR_<ENTITY>_NOT_FOUND."""
    store = getattr(db.db, collection)
    row = store.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError("ERR_%s_NOT_FOUND" % _ENTITY_KEYS[collection])
    return row


def fetch_body_fk(body, field, collection, required=False):
    """Rank 6: resolve a body foreign key in declared field order."""
    if field not in body or body[field] is None:
        if required:
            return None  # absence is a rank 7 concern, handled by the schema pass
        return None
    value = body[field]
    if not isinstance(value, str):
        return None  # wrong type is a rank 7 concern
    return fetch(collection, value)


# ---------------------------------------------------------------- query params


def enum_param(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        V.bad("Query parameter '%s' must be one of %s" % (name, ", ".join(sorted(allowed))))
    return raw


def bool_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    V.bad("Query parameter '%s' must be a boolean" % name)


def str_param(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def pagination():
    """Rank 8: ERR_INVALID_PAGINATION when out of range."""
    limit = response.PAGINATION_DEFAULT_LIMIT
    offset = response.PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            V.bad("Query parameter 'limit' must be an integer")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            V.bad("Query parameter 'offset' must be an integer")
    if limit < response.PAGINATION_MIN_LIMIT or limit > response.PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
