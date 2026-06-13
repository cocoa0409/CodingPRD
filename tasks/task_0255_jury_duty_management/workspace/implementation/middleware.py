"""Auth header extraction and role checking (PRD §2.1 / scaffold §1.7).

Every request carries two mandatory headers: X-User-ID and X-User-Role. The four
recognized roles are spelled exactly: JuryAdministrator, CourtClerk, Judge,
Juror. Missing X-User-ID, missing X-User-Role, or a role outside that set ->
ERR_UNAUTHENTICATED (401). A well-formed role not permitted for the operation ->
ERR_FORBIDDEN (403).
"""
from flask import request

import errors

VALID_ROLES = {"JuryAdministrator", "CourtClerk", "Judge", "Juror"}


def get_identity():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED on missing/invalid auth.

    Both headers must be present; X-User-Role must be one of the four declared
    roles (PRD §2.1).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.err(
            "ERR_UNAUTHENTICATED",
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN if `role` is not in the allowed set for the endpoint."""
    if role not in allowed:
        raise errors.err("ERR_FORBIDDEN", "Acting role not permitted for this operation")
