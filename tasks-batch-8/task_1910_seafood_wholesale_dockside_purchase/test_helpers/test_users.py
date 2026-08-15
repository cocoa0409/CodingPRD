"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (VesselAgent, Customer) carry an ownership identity:
`X-User-ID` must equal the acting Vessel's / Customer's `id` whenever the
call is ownership-gated. Use the per-instance builders for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls whose success does
# not depend on the caller owning the subject resource.
TEST_USERS = {
    "operations_manager_headers": build_user_headers("om_0", "OperationsManager"),
    "dock_buyer_headers": build_user_headers("db_0", "DockBuyer"),
    "grading_inspector_headers": build_user_headers("gi_0", "GradingInspector"),
    "inventory_planner_headers": build_user_headers("ip_0", "InventoryPlanner"),
    "logistics_coordinator_headers": build_user_headers("lc_0", "LogisticsCoordinator"),
    "compliance_officer_headers": build_user_headers("off_1", "ComplianceOfficer"),
    "any_headers": build_user_headers("any_0", "Any"),
    # Entity-backed fallbacks — only for calls that are NOT ownership-gated.
    "vessel_agent_headers": build_user_headers("va-shared", "VesselAgent"),
    "customer_headers": build_user_headers("cust-shared", "Customer"),
}

# Named operator identities used by segregation-of-duties scenarios (PRD §2.10).
OFFICER_1_HEADERS = build_user_headers("off_1", "ComplianceOfficer")
OFFICER_2_HEADERS = build_user_headers("off_2", "ComplianceOfficer")
OM_1_HEADERS = build_user_headers("om_1", "OperationsManager")
OM_2_HEADERS = build_user_headers("om_2", "OperationsManager")


def make_vessel_agent_headers(vessel_id: str) -> dict:
    """VesselAgent is entity-backed (PRD §2.1): pass the acting Vessel's id
    whenever the call is ownership-gated (ticket create / land)."""
    return build_user_headers(vessel_id, "VesselAgent")


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed (PRD §2.1): pass the acting Customer's id
    whenever the call is ownership-gated (order create / submit / cancel /
    add line)."""
    return build_user_headers(customer_id, "Customer")


def make_operations_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
