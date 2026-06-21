"""Auth header extraction and role checking (PRD §2.1, §2.6).

Two mandatory headers: X-User-ID and X-User-Role. Four valid roles. All roles
are entity-backed, but auth (ERR_UNAUTHENTICATED) only checks header presence
and that the role is one of the four recognized values; whether the X-User-ID
resolves to an existing entity is an ownership/existence concern handled per
endpoint at the appropriate validation priority.
"""

from flask import g, request

from errors import api_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"Requester", "FoiaOfficer", "AppealAuthority", "Submitter"}


def extract_identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise api_error(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID / X-User-Role header.")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """ERR_FORBIDDEN_ROLE unless the acting role is permitted for the op."""
    if g.user_role not in allowed:
        raise api_error(ERR_FORBIDDEN_ROLE, f"Role {g.user_role!r} is not permitted for this operation.")
