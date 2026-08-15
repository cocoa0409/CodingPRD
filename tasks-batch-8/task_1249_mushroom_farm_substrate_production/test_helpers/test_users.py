"""Pre-built role headers for every role in the PRD (§2.1).

HarvestCrewLead and BuyerPortal are entity-backed roles: their X-User-ID must
be the id of an existing Worker / Buyer respectively. Fixtures and tests that
perform ownership-gated calls MUST use the per-instance builders below with
the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for calls whose success does
# not depend on the caller owning the subject resource. For entity-backed
# roles (HarvestCrewLead, BuyerPortal) these are placeholders for
# non-ownership tests only.
TEST_USERS = {
    "farm_manager_headers": build_user_headers("test-farm-manager-1", "FarmManager"),
    "compost_supervisor_headers": build_user_headers("test-compost-supervisor-1", "CompostSupervisor"),
    "grading_inspector_headers": build_user_headers("test-grading-inspector-1", "GradingInspector"),
    "harvest_crew_lead_headers": build_user_headers("test-crew-lead-1", "HarvestCrewLead"),
    "payroll_clerk_headers": build_user_headers("test-payroll-clerk-1", "PayrollClerk"),
    "sales_manager_headers": build_user_headers("test-sales-manager-1", "SalesManager"),
    "quality_inspector_headers": build_user_headers("test-quality-inspector-1", "QualityInspector"),
    "buyer_portal_headers": build_user_headers("test-buyer-portal-1", "BuyerPortal"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


def make_harvest_crew_lead_headers(user_id: str) -> dict:
    """HarvestCrewLead is entity_backed by Worker: pass the real Worker.id
    whenever the call resolves the crew lead's identity."""
    return build_user_headers(user_id, "HarvestCrewLead")


def make_buyer_portal_headers(user_id: str) -> dict:
    """BuyerPortal is entity_backed by Buyer: pass the real Buyer.id whenever
    the call is ownership-gated (e.g. creating a commitment)."""
    return build_user_headers(user_id, "BuyerPortal")
