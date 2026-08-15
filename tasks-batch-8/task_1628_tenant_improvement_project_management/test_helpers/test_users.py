"""Pre-built role headers for every role in the PRD (section 2.1).

TenantRep and ContractorRep are entity-backed: their X-User-ID must equal the
id of the Tenant / Contractor they act for. Always build those headers with
make_tenant_rep_headers(tenant_id) / make_contractor_rep_headers(contractor_id)
using the real entity id returned by the create call; the shared constants are
fallbacks for tests that never exercise ownership (400/404 shape checks).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "landlord_pm_headers": build_user_headers("test-landlord-pm-1", "LandlordPM"),
    "landlord_approver_headers": build_user_headers("approver-1", "LandlordApprover"),
    "building_engineer_headers": build_user_headers("test-engineer-1", "BuildingEngineer"),
    # entity_backed fallbacks — non-ownership tests only:
    "tenant_rep_headers": build_user_headers("test-tenant-rep-1", "TenantRep"),
    "contractor_rep_headers": build_user_headers("test-contractor-rep-1", "ContractorRep"),
}


def make_tenant_rep_headers(user_id: str) -> dict:
    """For TenantRep (entity-backed by Tenant). Pass the actual Tenant.id as
    user_id whenever the call is ownership-gated (counter/accept, plan filing,
    tenant change orders, invoice pay/dispute)."""
    return build_user_headers(user_id, "TenantRep")


def make_contractor_rep_headers(user_id: str) -> dict:
    """For ContractorRep (entity-backed by Contractor). Pass the actual
    Contractor.id as user_id whenever the call is ownership-gated
    (acknowledge-rules, milestones, draws, waivers, punch work)."""
    return build_user_headers(user_id, "ContractorRep")


def make_landlord_approver_headers(user_id: str) -> dict:
    """For LandlordApprover (opaque identity). The X-User-ID is stamped into
    approved_by_user_id on change-order and draw approvals and later drives
    segregation-of-duties checks, so tests pick distinct approver ids on
    purpose."""
    return build_user_headers(user_id, "LandlordApprover")
