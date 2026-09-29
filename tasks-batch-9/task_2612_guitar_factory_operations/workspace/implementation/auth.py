"""Authentication, RBAC and the AuthorizedShop identity rules (PRD 2.1)."""

from flask import request

from errors import ApiError

PLANT_ADMIN = "PlantAdmin"
WOOD_BUYER = "WoodBuyer"
COMPLIANCE_OFFICER = "ComplianceOfficer"
MACHINIST = "Machinist"
LUTHIER = "Luthier"
QUALITY_INSPECTOR = "QualityInspector"
FINISH_TECH = "FinishTech"
CUSTOM_SHOP_COORDINATOR = "CustomShopCoordinator"
SERVICE_NETWORK_MANAGER = "ServiceNetworkManager"
AUTHORIZED_SHOP = "AuthorizedShop"

STAFF_ROLES = (
    PLANT_ADMIN,
    WOOD_BUYER,
    COMPLIANCE_OFFICER,
    MACHINIST,
    LUTHIER,
    QUALITY_INSPECTOR,
    FINISH_TECH,
    CUSTOM_SHOP_COORDINATOR,
    SERVICE_NETWORK_MANAGER,
)

ALL_ROLES = STAFF_ROLES + (AUTHORIZED_SHOP,)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "authentication headers missing")
    if user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID must not be empty")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unknown role")
    return user_id, role


def require(*allowed):
    """Rung 1 then rung 2 of the validation ladder."""
    user_id, role = authenticate()
    if allowed:
        flat = []
        for item in allowed:
            if isinstance(item, (list, tuple)):
                flat.extend(item)
            else:
                flat.append(item)
        if role not in flat:
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "role %s may not perform this operation" % role)
    return user_id, role


def require_staff():
    return require(STAFF_ROLES)
