"""Auth header extraction & role checking (PRD §2.1).

Every request carries X-User-ID and X-User-Role. The five roles are spelled
exactly: AccountHolder, Dispatcher, CrewTech, BillingAdmin, PlatformAdmin.
Missing/malformed -> 401 ERR_UNAUTHENTICATED. A well-formed but disallowed role
-> 403 ERR_FORBIDDEN_ROLE.

Registering an account holder and reading service-plan configuration are the
bootstrap operations that do not presuppose an established identity.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"AccountHolder", "Dispatcher", "CrewTech", "BillingAdmin", "PlatformAdmin"}

# Entity-backed roles compare X-User-ID against a persisted entity's id.
ENTITY_BACKED = {"AccountHolder", "CrewTech"}


def get_identity():
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED if either header is
    missing or malformed (role not one of the five recognized values, or a
    missing/empty user id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or role == "" or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed authentication headers.")
    if user_id is None or user_id == "":
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header.")

    return role, user_id


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role not in allowed."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Acting role is not permitted for this operation.")
