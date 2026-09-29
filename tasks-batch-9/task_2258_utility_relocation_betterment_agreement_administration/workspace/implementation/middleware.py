"""Authentication (rungs 1-2), path/body existence (rungs 4-5) and owner scope
(rung 6)."""
from flask import g, request

import db as store
from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "UtilityCoordinator",
    "RightOfWayAdjudicator",
    "AgreementOfficer",
    "ExternalAuditor",
    "ConstructionEngineer",
    "UtilityOwnerRep",
)

OWNER_REP = "UtilityOwnerRep"


def authenticate(allowed_roles):
    """Rung 1 then rung 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Header 'X-User-ID' is required.")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Header 'X-User-Role' must be one of the seven declared roles.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role '%s' may not invoke this endpoint." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


# ---------------------------------------------------------------- existence ---

_COLLECTIONS = {
    "project": ("projects", "ERR_PROJECT_NOT_FOUND"),
    "owner": ("owners", "ERR_OWNER_NOT_FOUND"),
    "facility": ("facilities", "ERR_FACILITY_NOT_FOUND"),
    "investigation": ("investigations", "ERR_INVESTIGATION_NOT_FOUND"),
    "conflict": ("conflicts", "ERR_CONFLICT_NOT_FOUND"),
    "determination": ("determinations", "ERR_DETERMINATION_NOT_FOUND"),
    "plan": ("plans", "ERR_PLAN_NOT_FOUND"),
    "permit": ("permits", "ERR_PERMIT_NOT_FOUND"),
    "slot": ("slots", "ERR_SLOT_NOT_FOUND"),
    "commitment": ("commitments", "ERR_COMMITMENT_NOT_FOUND"),
    "agreement": ("agreements", "ERR_AGREEMENT_NOT_FOUND"),
    "document": ("documents", "ERR_DOCUMENT_NOT_FOUND"),
    "finding": ("findings", "ERR_FINDING_NOT_FOUND"),
    "claim": ("claims", "ERR_CLAIM_NOT_FOUND"),
}


def must_get(kind, row_id):
    attr, error_id = _COLLECTIONS[kind]
    collection = getattr(store.db, attr)
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, "No %s exists with id '%s'." % (kind, row_id))
    return row


# -------------------------------------------------------------- owner scope ---

def check_owner_scope(owner_id):
    """Rung 6.  Only meaningful when the acting role is UtilityOwnerRep."""
    if g.get("role") != OWNER_REP:
        return
    if owner_id is None or g.get("user_id") != owner_id:
        raise ApiError("ERR_OWNER_SCOPE_VIOLATION",
                       "The acting representative does not act for the owner of this record.")


def owner_id_of_conflict(conflict):
    facility = store.db.facilities.get(conflict["facility_id"])
    return None if facility is None else facility["owner_id"]


def owner_id_of_plan(plan):
    conflict = store.db.conflicts.get(plan["conflict_id"])
    return None if conflict is None else owner_id_of_conflict(conflict)


def owner_id_of_determination(determination):
    conflict = store.db.conflicts.get(determination["conflict_id"])
    return None if conflict is None else owner_id_of_conflict(conflict)


def owner_id_of_document(document):
    agreement = store.db.agreements.get(document["agreement_id"])
    return None if agreement is None else agreement["owner_id"]
