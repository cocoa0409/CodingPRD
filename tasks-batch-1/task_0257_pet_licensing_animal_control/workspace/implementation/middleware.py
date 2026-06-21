"""Authentication & authorization (PRD §2.1, §2.6, SCAFFOLD §1.4 priority 1-2).

Headers (verbatim from PRD §2.1):
  X-User-ID    — the acting principal id
  X-User-Role  — one of: Owner, LicensingClerk, AnimalControlOfficer
"""
from flask import request

from errors import err

ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}


def authenticate():
    """Priority 1 (PRD §2.6): both headers present and role known, else
    ERR_UNAUTHENTICATED (401). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Priority 2 (PRD §2.6): role permitted for this operation, else
    ERR_UNAUTHORIZED (403)."""
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation.")


def require_owner_match(role, user_id, owner_id_of_resource):
    """Entity-backed ownership check for the Owner role (PRD §2.1).

    Only the Owner role is entity-backed; LicensingClerk and
    AnimalControlOfficer carry opaque ids that are never compared to entity ids.
    """
    if role == "Owner" and user_id != owner_id_of_resource:
        raise err("ERR_UNAUTHORIZED", "Owner does not own the target resource.")
