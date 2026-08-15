"""Pre-built role headers for every role in the PRD.

Opaque roles (staff) use shared constants. The Customer role is entity-backed:
any ownership-gated call MUST be made with make_customer_headers(customer["id"])
so that X-User-ID equals the actual Customer id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "csr_headers": build_user_headers("test-csr-1", "CustomerServiceRep"),
    "planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
    "operator_headers": build_user_headers("test-operator-1", "PressOperator"),
    "qa_headers": build_user_headers("qa-1", "QaInspector"),
    "qa2_headers": build_user_headers("qa-2", "QaInspector"),
    "pm_headers": build_user_headers("pm-1", "ProductionManager"),
    "pm2_headers": build_user_headers("pm-2", "ProductionManager"),
    "warehouse_headers": build_user_headers("test-wh-1", "WarehouseManager"),
    "billing_headers": build_user_headers("test-billing-1", "BillingClerk"),
    # Fallback for the entity-backed Customer role — only safe for calls whose
    # success does NOT depend on ownership (e.g. RBAC denial checks).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (confirm, TP review, proof decision)."""
    return build_user_headers(user_id, "Customer")


def make_qa_headers(user_id: str) -> dict:
    """QaInspector headers with a specific filer identity (SoD anchor)."""
    return build_user_headers(user_id, "QaInspector")


def make_pm_headers(user_id: str) -> dict:
    """ProductionManager headers with a specific decider identity."""
    return build_user_headers(user_id, "ProductionManager")
