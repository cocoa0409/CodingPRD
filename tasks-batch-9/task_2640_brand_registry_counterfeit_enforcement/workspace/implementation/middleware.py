"""Authentication and role-based access control (PRD 2.1)."""

from flask import request

import db
from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

BRAND_ADMINISTRATOR = "BrandAdministrator"
ENFORCEMENT_ANALYST = "EnforcementAnalyst"
AUTHORIZED_REPRESENTATIVE = "AuthorizedRepresentative"
MARKETPLACE_LIAISON = "MarketplaceLiaison"
CUSTOMS_COORDINATOR = "CustomsCoordinator"
LEGAL_COUNSEL = "LegalCounsel"

ROLES = (
    BRAND_ADMINISTRATOR,
    ENFORCEMENT_ANALYST,
    AUTHORIZED_REPRESENTATIVE,
    MARKETPLACE_LIAISON,
    CUSTOMS_COORDINATOR,
    LEGAL_COUNSEL,
)

ALL_ROLES = ROLES


class Identity(object):
    __slots__ = ("user_id", "role", "representative")

    def __init__(self, user_id, role, representative=None):
        self.user_id = user_id
        self.role = role
        self.representative = representative


def authenticate(*allowed_roles):
    """Priority 1 then priority 2 of the rejection ladder, followed by identity
    resolution for the entity-backed AuthorizedRepresentative role."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    allowed = allowed_roles[0] if len(allowed_roles) == 1 and isinstance(
        allowed_roles[0], (list, tuple, set, frozenset)) else allowed_roles
    if role not in allowed:
        fail("ERR_UNAUTHORIZED")
    rep = None
    if role == AUTHORIZED_REPRESENTATIVE:
        rep = db.get("representatives", user_id)
        if rep is None:
            fail("ERR_REPRESENTATIVE_NOT_FOUND")
    return Identity(user_id, role, rep)
