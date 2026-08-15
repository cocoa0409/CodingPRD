"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identifiers: the server never compares
X-User-ID against any resource id. Custom user ids are still needed wherever
actor attribution is compared — the segregation-of-duties rule (§3.3) matches
the screening resolver's X-User-ID against the waybill's submitted_by_user_id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for all six roles (all identities are opaque).
TEST_USERS = {
    "forwarder_ops_headers": build_user_headers("ops-1", "ForwarderOps"),
    "capacity_planner_headers": build_user_headers("planner-1", "CapacityPlanner"),
    "compliance_officer_headers": build_user_headers("comp-1", "ComplianceOfficer"),
    "customs_broker_headers": build_user_headers("broker-1", "CustomsBroker"),
    "pricing_manager_headers": build_user_headers("pricing-1", "PricingManager"),
    "claims_adjuster_headers": build_user_headers("adjuster-1", "ClaimsAdjuster"),
}


def make_forwarder_ops_headers(user_id: str) -> dict:
    """ForwarderOps headers with a specific user id (e.g. the submitting user)."""
    return build_user_headers(user_id, "ForwarderOps")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with a specific user id (e.g. the resolving officer)."""
    return build_user_headers(user_id, "ComplianceOfficer")
