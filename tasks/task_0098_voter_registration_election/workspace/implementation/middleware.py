"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. Five roles are recognized,
spelled exactly: ElectionAdmin, ElectionOfficial, Voter, PollWorker, Canvasser.

Four roles (ElectionAdmin/ElectionOfficial/PollWorker/Canvasser) carry an opaque
operator identifier the server never compares to any entity id. The Voter role
is entity-backed: X-User-ID is the id of a VoterRegistration the voter owns; any
ownership check compares a resource's registration FK to that id.
"""

from flask import g, request

from errors import unauthenticated, unauthorized

VALID_ROLES = {
    "ElectionAdmin",
    "ElectionOfficial",
    "Voter",
    "PollWorker",
    "Canvasser",
}


def extract_identity():
    """Parse X-User-ID and X-User-Role; raise ERR_UNAUTHENTICATED when missing
    or malformed (unknown role value)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise unauthenticated()
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Raise ERR_UNAUTHORIZED unless the acting role is one of `allowed`."""
    if g.user_role not in allowed:
        raise unauthorized(
            f"Role {g.user_role!r} is not authorized for this endpoint."
        )
