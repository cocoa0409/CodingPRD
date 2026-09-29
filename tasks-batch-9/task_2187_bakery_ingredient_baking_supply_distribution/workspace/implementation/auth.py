"""Authentication / RBAC guards (PRD §2.1, §2.7 precedence steps 1-3)."""
from flask import request

from errors import fail

ROLES = (
    "CustomerBuyer",
    "AccountManager",
    "PricingController",
    "WarehouseOperator",
    "QualityManager",
    "TechnicalSpecialist",
    "LogisticsPlanner",
    "PlatformAdmin",
)

ANY = tuple(ROLES)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_buyer(self):
        return self.role == "CustomerBuyer"


def authenticate(allowed_roles):
    """Header presence -> role recognition -> endpoint authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        fail("ERR_UNKNOWN_ROLE", "Unknown role: %s" % role)
    if allowed_roles is not None and role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint" % role)
    return Actor(user_id, role)


def require_owner(actor, owning_id):
    """CustomerBuyer ownership check (precedence step 7)."""
    if actor.role == "CustomerBuyer" and actor.user_id != owning_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Acting principal does not own this resource")
