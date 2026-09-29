"""
Actor headers for every role that may call this API.

Nine roles are opaque: their `X-User-ID` is an arbitrary stable string, so the
canonical operators are pinned here and a segregation-of-duties or
measurement-ownership assertion can name exactly who acted. The tenth role is
entity-backed: when `X-User-Role` is `AuthorizedShop`, `X-User-ID` is the `id`
of the acting repair shop row, so its headers can only be built once that row
exists.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

# ---------------------------------------------------------------------------
# Role names, spelled exactly as X-User-Role must carry them
# ---------------------------------------------------------------------------
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

STAFF_ROLES = [
    PLANT_ADMIN,
    WOOD_BUYER,
    COMPLIANCE_OFFICER,
    MACHINIST,
    LUTHIER,
    QUALITY_INSPECTOR,
    FINISH_TECH,
    CUSTOM_SHOP_COORDINATOR,
    SERVICE_NETWORK_MANAGER,
]

ALL_ROLES = STAFF_ROLES + [AUTHORIZED_SHOP]

# ---------------------------------------------------------------------------
# Canonical operator identifiers for the opaque roles
# ---------------------------------------------------------------------------
PLANT_ADMIN_ID = "pa-adam"
WOOD_BUYER_ID = "wb-wendy"
COMPLIANCE_OFFICER_ID = "co-alice"
COMPLIANCE_OFFICER_2_ID = "co-gina"
COMPLIANCE_OFFICER_3_ID = "co-hank"
MACHINIST_ID = "ma-mike"
LUTHIER_ID = "lu-eve"
LUTHIER_2_ID = "lu-zoe"
QUALITY_INSPECTOR_ID = "qi-frank"
QUALITY_INSPECTOR_2_ID = "qi-ivan"
FINISH_TECH_ID = "ft-fiona"
COORDINATOR_ID = "csc-bob"
COORDINATOR_2_ID = "csc-dana"
COORDINATOR_3_ID = "cs-gwen"
COORDINATOR_4_ID = "cs-hana"
SERVICE_MANAGER_ID = "sn-sam"

# ---------------------------------------------------------------------------
# Ready-made header dicts for the opaque roles
# ---------------------------------------------------------------------------
PLANT_ADMIN_HEADERS = build_user_headers(PLANT_ADMIN_ID, PLANT_ADMIN)
WOOD_BUYER_HEADERS = build_user_headers(WOOD_BUYER_ID, WOOD_BUYER)
COMPLIANCE_HEADERS = build_user_headers(COMPLIANCE_OFFICER_ID, COMPLIANCE_OFFICER)
COMPLIANCE_2_HEADERS = build_user_headers(COMPLIANCE_OFFICER_2_ID, COMPLIANCE_OFFICER)
COMPLIANCE_3_HEADERS = build_user_headers(COMPLIANCE_OFFICER_3_ID, COMPLIANCE_OFFICER)
MACHINIST_HEADERS = build_user_headers(MACHINIST_ID, MACHINIST)
LUTHIER_HEADERS = build_user_headers(LUTHIER_ID, LUTHIER)
LUTHIER_2_HEADERS = build_user_headers(LUTHIER_2_ID, LUTHIER)
INSPECTOR_HEADERS = build_user_headers(QUALITY_INSPECTOR_ID, QUALITY_INSPECTOR)
INSPECTOR_2_HEADERS = build_user_headers(QUALITY_INSPECTOR_2_ID, QUALITY_INSPECTOR)
FINISH_TECH_HEADERS = build_user_headers(FINISH_TECH_ID, FINISH_TECH)
COORDINATOR_HEADERS = build_user_headers(COORDINATOR_ID, CUSTOM_SHOP_COORDINATOR)
COORDINATOR_2_HEADERS = build_user_headers(COORDINATOR_2_ID, CUSTOM_SHOP_COORDINATOR)
COORDINATOR_3_HEADERS = build_user_headers(COORDINATOR_3_ID, CUSTOM_SHOP_COORDINATOR)
COORDINATOR_4_HEADERS = build_user_headers(COORDINATOR_4_ID, CUSTOM_SHOP_COORDINATOR)
SERVICE_MANAGER_HEADERS = build_user_headers(SERVICE_MANAGER_ID, SERVICE_NETWORK_MANAGER)

HEADERS_BY_ROLE = {
    PLANT_ADMIN: PLANT_ADMIN_HEADERS,
    WOOD_BUYER: WOOD_BUYER_HEADERS,
    COMPLIANCE_OFFICER: COMPLIANCE_HEADERS,
    MACHINIST: MACHINIST_HEADERS,
    LUTHIER: LUTHIER_HEADERS,
    QUALITY_INSPECTOR: INSPECTOR_HEADERS,
    FINISH_TECH: FINISH_TECH_HEADERS,
    CUSTOM_SHOP_COORDINATOR: COORDINATOR_HEADERS,
    SERVICE_NETWORK_MANAGER: SERVICE_MANAGER_HEADERS,
}


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary caller identifier under an arbitrary role."""
    return build_user_headers(user_id, role)


def make_authorized_shop_headers(shop_id: str) -> Headers:
    """
    Headers for the entity-backed external role: `X-User-ID` must be the `id`
    of the acting repair shop row, because ownership checks compare the
    resource's shop reference to it directly.
    """
    return build_user_headers(shop_id, AUTHORIZED_SHOP)


def staff_headers_except(*roles: str) -> dict:
    """The canonical staff header dicts for every staff role but the named ones."""
    return {r: h for r, h in HEADERS_BY_ROLE.items() if r not in roles}


NO_ROLE_HEADERS = {"X-User-ID": PLANT_ADMIN_ID, "Content-Type": "application/json"}
NO_USER_HEADERS = {"X-User-Role": PLANT_ADMIN, "Content-Type": "application/json"}
EMPTY_USER_HEADERS = build_user_headers("", PLANT_ADMIN)
UNKNOWN_ROLE_HEADERS = build_user_headers(PLANT_ADMIN_ID, "FactoryManager")
