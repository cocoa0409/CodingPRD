"""Pre-built role headers for every role in the PRD.

Opaque roles (all except Customer) use shared constants: the server records the
identifier but never compares it to any entity id. The Customer role is
entity-backed: ownership checks compare X-User-ID to the Customer id, so any
ownership-gated call MUST use make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "sales_rep_headers": build_user_headers("test-salesrep-1", "SalesRep"),
    "assessor_headers": build_user_headers("test-assessor-1", "Assessor"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "AssessmentReviewer"),
    "funding_officer_headers": build_user_headers("test-funding-1", "FundingOfficer"),
    "install_coordinator_headers": build_user_headers("test-coordinator-1",
                                                      "InstallCoordinator"),
    "inventory_manager_headers": build_user_headers("test-inventory-1",
                                                    "InventoryManager"),
    "claims_adjuster_headers": build_user_headers("test-claims-1", "ClaimsAdjuster"),
    # Fallback for the entity-backed Customer role: ONLY safe for calls whose
    # success does not depend on owning the subject resource.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (accept own quotes, pay own
    agreements, file funding applications or claims on own resources)."""
    return build_user_headers(user_id, "Customer")
