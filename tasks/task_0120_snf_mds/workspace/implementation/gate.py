"""Per-route auth+RBAC gate (PRD §2.7 priorities 1-2).

Usage at the top of every handler:
    gate(["Administrator"])
This enforces authentication (both headers present) then authorization (role
permitted), in that order, before any existence / body / state / business check.
"""
from middleware import get_identity, require_role


def gate(allowed_roles):
    """Run priority-1 auth then priority-2 authorization. Returns (user_id, role)."""
    user_id, role = get_identity()
    require_role(role, allowed_roles)
    return user_id, role
