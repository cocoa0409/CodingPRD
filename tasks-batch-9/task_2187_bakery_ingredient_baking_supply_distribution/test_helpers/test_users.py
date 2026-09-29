"""Pre-built role headers for the eight roles of PRD §2.1.

`CustomerBuyer` is the one role whose `X-User-ID` is the `id` of a persisted
`Customer` (PRD §2.1). Every ownership-gated call therefore MUST use
``make_customer_buyer_headers(customer["id"])`` with a real customer id — the
shared ``TEST_USERS["customer_buyer_headers"]`` constant is only safe for tests
that never reach an ownership comparison (auth/role/validation failures).

The other seven roles carry opaque operator identifiers, so the shared
constants below are the canonical form for them. Where segregation of duties
matters (PRD §2.1) tests need two *distinct* operator ids for the same role;
the ``make_<role>_headers`` builders provide them.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers reused across fixtures.
ACCOUNT_MANAGER_USER_ID = "am-1"
PRICING_CONTROLLER_USER_ID = "pc-1"
WAREHOUSE_OPERATOR_USER_ID = "wo-1"
QUALITY_MANAGER_USER_ID = "qm-1"
TECHNICAL_SPECIALIST_USER_ID = "ts-1"
LOGISTICS_PLANNER_USER_ID = "lp-1"
PLATFORM_ADMIN_USER_ID = "adm-1"

TEST_USERS = {
    # entity_backed:Customer — fallback for non-ownership tests only.
    "customer_buyer_headers": build_user_headers("test-buyer-1", "CustomerBuyer"),
    # opaque roles — canonical form.
    "account_manager_headers": build_user_headers(ACCOUNT_MANAGER_USER_ID, "AccountManager"),
    "pricing_controller_headers": build_user_headers(PRICING_CONTROLLER_USER_ID, "PricingController"),
    "warehouse_operator_headers": build_user_headers(WAREHOUSE_OPERATOR_USER_ID, "WarehouseOperator"),
    "quality_manager_headers": build_user_headers(QUALITY_MANAGER_USER_ID, "QualityManager"),
    "technical_specialist_headers": build_user_headers(TECHNICAL_SPECIALIST_USER_ID, "TechnicalSpecialist"),
    "logistics_planner_headers": build_user_headers(LOGISTICS_PLANNER_USER_ID, "LogisticsPlanner"),
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
}


def make_customer_buyer_headers(user_id: str) -> dict:
    """For CustomerBuyer (entity_backed:Customer).

    Pass the acting ``Customer.id`` — PRD §2.1 compares the resource's
    ``customer_id`` to ``X-User-ID`` for this role.
    """
    return build_user_headers(user_id, "CustomerBuyer")


def make_account_manager_headers(user_id: str = ACCOUNT_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_pricing_controller_headers(user_id: str = PRICING_CONTROLLER_USER_ID) -> dict:
    return build_user_headers(user_id, "PricingController")


def make_warehouse_operator_headers(user_id: str = WAREHOUSE_OPERATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_quality_manager_headers(user_id: str = QUALITY_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "QualityManager")


def make_technical_specialist_headers(user_id: str = TECHNICAL_SPECIALIST_USER_ID) -> dict:
    return build_user_headers(user_id, "TechnicalSpecialist")


def make_logistics_planner_headers(user_id: str = LOGISTICS_PLANNER_USER_ID) -> dict:
    return build_user_headers(user_id, "LogisticsPlanner")


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
