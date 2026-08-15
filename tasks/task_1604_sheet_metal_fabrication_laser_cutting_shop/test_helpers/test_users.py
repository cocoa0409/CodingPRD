"""Pre-built role headers for every role in PRD §2.1.

CustomerRep is entity-backed: its X-User-ID must be the acting Customer's id
whenever the call is ownership-gated (quote accept/reject, order payment).
Use make_customer_rep_headers(customer["id"]) for those calls; the shared
constant is only safe for negative RBAC probes.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "shop_manager_headers": build_user_headers("mgr-1", "ShopManager"),
    "estimator_headers": build_user_headers("est-1", "Estimator"),
    # entity_backed:Customer — fallback for non-ownership probes only.
    "customer_rep_headers": build_user_headers("rep-orphan-1", "CustomerRep"),
    "planner_headers": build_user_headers("planner-1", "ProductionPlanner"),
    "operator_headers": build_user_headers("op-default", "MachineOperator"),
    "qc_inspector_headers": build_user_headers("qc-1", "QCInspector"),
    "inventory_clerk_headers": build_user_headers("clerk-1", "InventoryClerk"),
}

# Headers carrying a well-formed id but a role value outside the declared set.
ANONYMOUS_HEADERS = {"X-User-ID": "anon-1", "Content-Type": "application/json"}
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_customer_rep_headers(customer_id: str) -> dict:
    """CustomerRep is entity-backed by Customer: pass the acting customer's id
    whenever the call is ownership-gated (accept / reject / payment)."""
    return build_user_headers(customer_id, "CustomerRep")


def make_operator_headers(user_id: str) -> dict:
    """MachineOperator identity is opaque but recorded as completing_operator_id."""
    return build_user_headers(user_id, "MachineOperator")


def make_qc_inspector_headers(user_id: str) -> dict:
    """QCInspector identity is recorded as inspector_id on inspection reports."""
    return build_user_headers(user_id, "QCInspector")
