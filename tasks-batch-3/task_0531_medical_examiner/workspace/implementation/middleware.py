"""Auth, RBAC and request-parsing helpers.

Auth header names come from PRD §2.1: X-User-ID and X-User-Role. Roles are exactly:
Admin, Investigator, Pathologist, MedicalExaminer, LabTech, Anonymous.
"""
from flask import request

import errors
from db import db

ROLES = {"Admin", "Investigator", "Pathologist", "MedicalExaminer", "LabTech", "Anonymous"}

# Roles that are backed by a persisted entity (X-User-ID must resolve).
ENTITY_BACKED = {
    "Investigator": "investigators",
    "Pathologist": "pathologists",
    "MedicalExaminer": "pathologists",
}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def _header(name):
    v = request.headers.get(name)
    if v is not None and v == "":
        return None
    return v


def authenticate():
    """Validate headers and role recognition (validation priorities 1-2).

    Returns (user_id, role). Does NOT do RBAC or identity resolution.
    """
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if not user_id or not role:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unknown role")
    return user_id, role


def require(allowed_roles):
    """Full auth + RBAC + entity-identity resolution.

    Order (PRD §2.12): authentication -> role authorization -> entity-identity.
    `allowed_roles` is the set of roles permitted for the operation.
    Returns an Actor.
    """
    user_id, role = authenticate()

    # priority 10: role authorization
    if role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")

    # priority 11: entity-identity resolution for entity-backed roles
    _resolve_identity(user_id, role)

    return Actor(user_id, role)


def _resolve_identity(user_id, role):
    store_name = ENTITY_BACKED.get(role)
    if store_name is None:
        return
    store = getattr(db, store_name)
    record = store.get(user_id)
    if record is None:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Acting identity does not resolve to a known record")
    # A MedicalExaminer must be a Pathologist whose is_medical_examiner flag is true.
    if role == "MedicalExaminer" and not record.get("is_medical_examiner", False):
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Acting pathologist is not a medical examiner")


# ---- request body / query helpers ----

def json_body():
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
        return data
    return {}


def pagination():
    """Parse limit/offset (PRD §2.3). Defaults 10 / 0, min 1, max 100."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows):
    """Sort by creation order, then slice per pagination params.

    Returns (page_items, limit, offset, total_count).
    """
    limit, offset = pagination()
    rows = sorted(rows, key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total
