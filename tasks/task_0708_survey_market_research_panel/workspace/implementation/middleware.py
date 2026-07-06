"""Auth header extraction and RBAC (PRD §2.1, scaffold §1.4 priorities 1-2).

Every request carries X-User-ID and X-User-Role. The four roles are spelled
exactly ResearchManager, PanelOps, FieldCoordinator, Panelist. Missing either
header, or an unknown role -> ERR_UNAUTHENTICATED (401). A well-formed but
unauthorized role -> ERR_FORBIDDEN_ROLE (403).

ResearchManager / PanelOps / FieldCoordinator have opaque operator identities
(X-User-ID never compared to an entity id). Panelist is entity-backed:
X-User-ID is the acting Panelist's id; ownership checks compare a target
resource's panelist_id to X-User-ID -> ERR_NOT_RESOURCE_OWNER (403).
"""
from flask import request

import errors

ROLES = {"ResearchManager", "PanelOps", "FieldCoordinator", "Panelist"}


def get_identity():
    """Return (user_id, role) after validating presence + known role (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED,
                    "Missing or unknown X-User-ID / X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (priority 2): the acting role must be permitted for this op."""
    if role not in allowed:
        errors.fail(errors.ERR_FORBIDDEN_ROLE,
                    "Role %s is not permitted for this operation" % role)


def require_owner(user_id, role, owner_panelist_id):
    """Ownership check (priority 4) for entity-backed Panelist actions.

    Only enforced when the acting role is Panelist; operator roles act by role
    authority. The acting Panelist may only operate on resources whose
    panelist_id equals X-User-ID.
    """
    if role == "Panelist" and owner_panelist_id != user_id:
        errors.fail(errors.ERR_NOT_RESOURCE_OWNER,
                    "Panelist may only act on their own resources")
