"""Auth header extraction and role checking (PRD §2.1, §2.8).

Every request must carry two mandatory headers: X-User-ID and X-User-Role.
Missing/malformed -> ERR_MISSING_AUTH (401). Present but role not permitted for
the operation -> ERR_FORBIDDEN_ROLE (403). All four roles are opaque operator
capacities; X-User-ID is never compared to any entity id.
"""
from __future__ import annotations

from typing import Optional
from flask import request, g

from errors import err

# The four roles, spelled precisely (PRD §2.1).
VALID_ROLES = {"QualityManager", "ReceivingClerk", "ProductionOperator", "SafetyAuditor"}


def require_auth(allowed_roles):
    """Authenticate headers then authorize the role.

    Priority 1 (auth): both headers present and the role is a recognized value
    (well-formed) -> else ERR_MISSING_AUTH (401).
    Priority 2 (role): role permitted for this operation -> else
    ERR_FORBIDDEN_ROLE (403).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    # Headers present and well-formed. A blank value or an unrecognized role
    # value is treated as malformed auth.
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH", "X-User-ID and X-User-Role headers required")

    g.user_id = user_id
    g.user_role = role

    if role not in set(allowed_roles):
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
