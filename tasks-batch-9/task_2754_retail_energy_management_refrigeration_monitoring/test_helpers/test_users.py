"""Pre-built role headers for every operator role named by the PRD.

The PRD identifies the caller with the X-User-ID and X-User-Role headers.
Five roles carry an opaque identifier; StoreManager and BmsGateway carry the
identifier of the Store they act for, so ownership-gated calls MUST use the
per-instance builders below with the real store id.
"""
from prd_bench_local_runner.testing import build_user_headers

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_ENERGY_MANAGER = "EnergyManager"
ROLE_ENERGY_ANALYST = "EnergyAnalyst"
ROLE_STORE_MANAGER = "StoreManager"
ROLE_FOOD_SAFETY_OFFICER = "FoodSafetyOfficer"
ROLE_MAINTENANCE_TECH = "MaintenanceTech"
ROLE_BMS_GATEWAY = "BmsGateway"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_ENERGY_MANAGER,
    ROLE_ENERGY_ANALYST,
    ROLE_STORE_MANAGER,
    ROLE_FOOD_SAFETY_OFFICER,
    ROLE_MAINTENANCE_TECH,
    ROLE_BMS_GATEWAY,
]

# Shared constants. Safe for the five opaque roles, and for any test whose
# outcome does not depend on the caller owning the subject store.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("u_admin_1", ROLE_PLATFORM_ADMIN),
    "energy_manager_headers": build_user_headers("u_manager_1", ROLE_ENERGY_MANAGER),
    "energy_analyst_headers": build_user_headers("u_analyst_1", ROLE_ENERGY_ANALYST),
    "store_manager_headers": build_user_headers("u_store_mgr_1", ROLE_STORE_MANAGER),
    "food_safety_officer_headers": build_user_headers(
        "u_fso_1", ROLE_FOOD_SAFETY_OFFICER
    ),
    "maintenance_tech_headers": build_user_headers("u_tech_1", ROLE_MAINTENANCE_TECH),
    "bms_gateway_headers": build_user_headers("u_gateway_1", ROLE_BMS_GATEWAY),
}

# A request that carries no X-User-ID at all.
NO_IDENTITY_HEADERS = {"X-User-Role": ROLE_PLATFORM_ADMIN, "Content-Type": "application/json"}
EMPTY_IDENTITY_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": ROLE_PLATFORM_ADMIN,
    "Content-Type": "application/json",
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_energy_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_ENERGY_MANAGER)


def make_energy_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_ENERGY_ANALYST)


def make_store_manager_headers(user_id: str) -> dict:
    """For StoreManager, whose X-User-ID is the id of the store it manages.
    Pass the real Store.id whenever the call is store-scoped."""
    return build_user_headers(user_id, ROLE_STORE_MANAGER)


def make_food_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_FOOD_SAFETY_OFFICER)


def make_maintenance_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, ROLE_MAINTENANCE_TECH)


def make_bms_gateway_headers(user_id: str) -> dict:
    """For BmsGateway, whose X-User-ID is the id of the store it serves.
    Pass the real Store.id whenever the call is store-scoped."""
    return build_user_headers(user_id, ROLE_BMS_GATEWAY)


def make_headers_for_role(role: str, user_id: str) -> dict:
    return build_user_headers(user_id, role)
