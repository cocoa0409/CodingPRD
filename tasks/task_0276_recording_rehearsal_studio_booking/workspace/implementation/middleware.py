"""Auth header extraction & role checks (PRD §2.1)."""
from flask import request

from errors import err

VALID_ROLES = {"StudioManager", "Client", "Engineer", "Anonymous"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_principal(open_endpoint=False):
    """Extract and validate X-User-ID / X-User-Role headers (PRD §2.1).

    Both headers are mandatory and must be well-formed (non-empty, recognized
    role). Missing/malformed -> ERR_UNAUTHENTICATED.

    `open_endpoint=True` is used for the two deliberately-open bootstrap
    operations (POST /studio and POST /studio/clients/register). Per PRD §2.1
    and scaffold validation priority 1, these are exempt from the auth check so
    a brand-new studio/client can come into existence before any credentialed
    principal exists. If headers are absent we synthesize an Anonymous
    principal; if present and well-formed we honor them; a present-but-malformed
    role is still rejected.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if open_endpoint and user_id is None and role is None:
        return Principal("anonymous", "Anonymous")

    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise err("ERR_UNAUTHENTICATED", "empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "unrecognized role: %s" % role)
    return Principal(user_id, role)


def require_roles(principal, allowed_roles):
    """Enforce the role permission gate (ERR_FORBIDDEN)."""
    if principal.role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "role %s not permitted" % principal.role)
