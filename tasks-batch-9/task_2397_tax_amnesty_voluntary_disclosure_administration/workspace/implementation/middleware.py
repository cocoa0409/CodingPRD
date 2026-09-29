"""Identity, authorization, ownership and segregation of duties.

Implements precedence rules 1-7 of PRD 2.6.  Every route calls identity()
first, then resolves its path ids, then its body foreign keys, then ownership,
and only then looks at the request body.
"""

from flask import request

import db
from errors import err

PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
DISCLOSURE_OFFICER = "DisclosureOfficer"
COMPLIANCE_AUDITOR = "ComplianceAuditor"
REPRESENTATIVE = "Representative"
TAXPAYER = "Taxpayer"

KNOWN_ROLES = (
    PROGRAM_ADMINISTRATOR,
    DISCLOSURE_OFFICER,
    COMPLIANCE_AUDITOR,
    REPRESENTATIVE,
    TAXPAYER,
)

EVERY_ROLE = KNOWN_ROLES


def identity(allowed_roles):
    """Rules 1-4.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED")
    if role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE")
    if role == TAXPAYER and user_id not in db.taxpayers:
        raise err("ERR_IDENTITY_NOT_RECOGNIZED")
    if role == REPRESENTATIVE and user_id not in db.representatives:
        raise err("ERR_IDENTITY_NOT_RECOGNIZED")
    return user_id, role


# =============================================================================
# path and body id resolution (rules 5 and 6)
# =============================================================================
def find(collection, row_id, error_id):
    rec = collection.get(row_id)
    if rec is None:
        raise err(error_id)
    return rec


def body_fk(body, field, collection, error_id):
    """Rule 6: resolve a supplied foreign key, or defer to schema validation.

    A missing, null or non-string value is left to rule 8 so the caller sees
    ERR_INVALID_REQUEST rather than a 404 for something it never sent.
    """
    if field not in body:
        return None
    raw = body[field]
    if raw is None or not isinstance(raw, str):
        return None
    rec = collection.get(raw)
    if rec is None:
        raise err(error_id)
    return rec


# =============================================================================
# ownership (rule 7 and the ERR_NOT_RESOURCE_OWNER endpoints of 1.5)
# =============================================================================
def representative_of_agreement(agreement):
    pre_clearance_id = agreement.get("pre_clearance_id")
    if not pre_clearance_id:
        return None
    pre_clearance = db.pre_clearances.get(pre_clearance_id)
    if pre_clearance is None:
        return None
    return pre_clearance["representative_id"]


def require_agreement_owner(agreement, user_id, role):
    if role == TAXPAYER:
        if agreement["taxpayer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER")
    elif role == REPRESENTATIVE:
        if representative_of_agreement(agreement) != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER")
    return agreement


def require_pre_clearance_owner(pre_clearance, user_id, role):
    if role == REPRESENTATIVE and pre_clearance["representative_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER")
    return pre_clearance


def require_taxpayer_self(taxpayer, user_id, role):
    if role == TAXPAYER and taxpayer["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER")
    return taxpayer


def require_segregation(prepared_by_user_id, user_id):
    """Rule 22: the preparer may not approve their own record."""
    if prepared_by_user_id is not None and prepared_by_user_id == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES")


# =============================================================================
# query-string list filters
# =============================================================================
def filter_equals(rows, field, param=None):
    raw = request.args.get(param or field)
    if raw is None:
        return rows
    return [r for r in rows if r.get(field) == raw]


def filter_flag(rows, field):
    raw = request.args.get(field)
    if raw is None:
        return rows
    wanted = raw.strip().lower() == "true"
    return [r for r in rows if bool(r.get(field)) == wanted]
