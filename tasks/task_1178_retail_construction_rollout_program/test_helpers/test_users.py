"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership of a caller-owned resource. For GCVendor (entity-backed by
# Contractor) the shared constant is only for non-ownership calls; any bid
# submit/withdraw must use make_gc_vendor_headers(contractor_id).
TEST_USERS = {
    "program_director_headers": build_user_headers("test-director-1", "ProgramDirector"),
    "design_manager_headers": build_user_headers("test-design-1", "DesignManager"),
    "permit_coordinator_headers": build_user_headers("test-permit-1", "PermitCoordinator"),
    "procurement_lead_headers": build_user_headers("test-procurement-1", "ProcurementLead"),
    "gc_vendor_headers": build_user_headers("test-gc-vendor-1", "GCVendor"),
    "site_superintendent_headers": build_user_headers("test-superintendent-1", "SiteSuperintendent"),
    "operations_lead_headers": build_user_headers("test-operations-1", "OperationsLead"),
    "finance_controller_headers": build_user_headers("test-finance-1", "FinanceController"),
}


def make_program_director_headers(user_id: str) -> dict:
    """ProgramDirector with a specific opaque operator id."""
    return build_user_headers(user_id, "ProgramDirector")


def make_design_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DesignManager")


def make_permit_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PermitCoordinator")


def make_procurement_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcurementLead")


def make_gc_vendor_headers(user_id: str) -> dict:
    """GCVendor is entity-backed by Contractor: pass the actual Contractor.id
    as user_id whenever the call is ownership-gated (bid submit/withdraw)."""
    return build_user_headers(user_id, "GCVendor")


def make_site_superintendent_headers(user_id: str) -> dict:
    """SiteSuperintendent with a specific opaque operator id. Use this to pin
    proposed_by_user_id on change-order proposals."""
    return build_user_headers(user_id, "SiteSuperintendent")


def make_operations_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsLead")


def make_finance_controller_headers(user_id: str) -> dict:
    """FinanceController with a specific opaque operator id. Use this to pin
    the approver identity for segregation-of-duties scenarios."""
    return build_user_headers(user_id, "FinanceController")
