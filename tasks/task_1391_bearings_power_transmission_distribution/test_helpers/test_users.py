"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Entity-backed roles MUST use the per-instance builders below
# whenever the call is ownership-gated.
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    "pricing_analyst_headers": build_user_headers("test-pricing-1", "PricingAnalyst"),
    "contract_admin_headers": build_user_headers("test-contract-admin-1", "ContractAdministrator"),
    "counter_sales_rep_headers": build_user_headers("test-csr-1", "CounterSalesRep"),
    "branch_manager_headers": build_user_headers("test-bm-1", "BranchManager"),
    "on_call_technician_headers": build_user_headers("test-tech-1", "OnCallTechnician"),
    "warranty_analyst_headers": build_user_headers("test-wa-1", "WarrantyAnalyst"),
    "quality_engineer_headers": build_user_headers("test-qe-1", "QualityEngineer"),
    # Entity-backed roles: shared constants are a fallback for non-ownership tests only.
    "customer_plant_headers": build_user_headers("test-customer-plant-1", "CustomerPlant"),
    "service_shop_headers": build_user_headers("test-service-shop-1", "ServiceShop"),
}


# Per-instance builders — required for entity-backed roles.
def make_customer_plant_headers(user_id: str) -> dict:
    """For CustomerPlant (entity-backed by CustomerAccount). Pass the actual
    CustomerAccount.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustomerPlant")


def make_service_shop_headers(user_id: str) -> dict:
    """For ServiceShop (entity-backed by ServiceShop). Pass the actual
    ServiceShop.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ServiceShop")
