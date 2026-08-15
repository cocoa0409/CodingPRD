"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. DealerPrincipal is entity-backed: ownership-gated calls MUST use
make_dealer_principal_headers(<dealer id>) with the real Dealer.id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "system_admin_headers": build_user_headers("test-admin-1", "SystemAdmin"),
    "allocation_manager_headers": build_user_headers(
        "test-alloc-1", "AllocationManager"
    ),
    "production_planner_headers": build_user_headers(
        "test-planner-1", "ProductionPlanner"
    ),
    "compliance_officer_headers": build_user_headers(
        "test-officer-1", "ComplianceOfficer"
    ),
    "warranty_administrator_headers": build_user_headers(
        "test-warranty-1", "WarrantyAdministrator"
    ),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "dealer_principal_headers": build_user_headers(
        "test-dealer-1", "DealerPrincipal"
    ),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


def make_dealer_principal_headers(user_id: str) -> dict:
    """DealerPrincipal is entity-backed: pass the acting Dealer.id as user_id
    whenever the call is ownership-gated (orders, curtailments, registrations,
    claims)."""
    return build_user_headers(user_id, "DealerPrincipal")


def make_production_planner_headers(user_id: str) -> dict:
    """ProductionPlanner with an explicit opaque user id; the id is stamped as
    hull created_by_user_id, which anchors the certification segregation check."""
    return build_user_headers(user_id, "ProductionPlanner")


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with an explicit opaque user id; certification requires
    this id to differ from the hull's created_by_user_id."""
    return build_user_headers(user_id, "ComplianceOfficer")
