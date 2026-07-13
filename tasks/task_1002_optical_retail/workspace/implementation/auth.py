"""Authentication / RBAC (PRD 2.1, validation priorities 1, 2 and 6)."""
from flask import request

from errors import err

ROLES = (
    "Customer",
    "OpticianVerifier",
    "StoreAssociate",
    "LabTechnician",
    "BenefitsAdmin",
    "PlatformAdmin",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == "Customer"


def authenticate(*allowed_roles):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED")
    return Actor(user_id, role)


def require_owner(actor, customer_id):
    """Priority 6 -- a Customer may only touch resources whose customer_id is theirs."""
    if actor.is_customer and customer_id != actor.user_id:
        raise err("ERR_UNAUTHORIZED")
