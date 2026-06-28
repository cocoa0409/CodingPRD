"""Auth header extraction & role checking (PRD §2.1, §2.10).

Every request carries X-User-ID and X-User-Role. The four roles are spelled
exactly BoxManager, Coach, Member, Anonymous. Missing/malformed -> 401
ERR_UNAUTHENTICATED (except member self-registration). A well-formed but
disallowed role -> 403 ERR_FORBIDDEN_ROLE.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"BoxManager", "Coach", "Member", "Anonymous"}


def get_identity(require_id=True):
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED if headers missing
    or malformed.

    X-User-ID may be omitted only for Anonymous and opaque-role audit-less
    calls; for Member/Coach a present, non-empty X-User-ID identifies the
    acting entity. Role header is always required and must be one of the four.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or role == "" or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed authentication headers.")

    # For entity-backed roles, X-User-ID must be present and well-formed.
    if role in ("Member", "Coach"):
        if user_id is None or user_id == "":
            raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID for entity-backed role.")

    return role, user_id


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role not in allowed."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Acting role is not permitted for this operation.")
