"""Pre-built role headers for every role in the PRD (§2.1).

Three roles carry an opaque identity (FoodBankOperator, AllocationManager,
ComplianceAuditor): their X-User-ID is not tied to any entity, so the shared
constant is the canonical form. The AgencyCoordinator role is entity_backed
(its X-User-ID is the acting Agency.id); ownership-gated calls MUST use
make_agency_coordinator_headers(agency_id) with the real Agency id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque roles use these directly; the AgencyCoordinator
# shared constant is only a fallback for non-ownership tests (e.g. 401/403/422
# checks where no real agency owns the target).
TEST_USERS = {
    "food_bank_operator_headers": build_user_headers("op-1", "FoodBankOperator"),
    "allocation_manager_headers": build_user_headers("mgr-1", "AllocationManager"),
    "compliance_auditor_headers": build_user_headers("auditor-1", "ComplianceAuditor"),
    "agency_coordinator_headers": build_user_headers("coordinator-1", "AgencyCoordinator"),
}


def make_food_bank_operator_headers(user_id: str = "op-1") -> dict:
    """FoodBankOperator (opaque identity)."""
    return build_user_headers(user_id, "FoodBankOperator")


def make_allocation_manager_headers(user_id: str = "mgr-1") -> dict:
    """AllocationManager (opaque identity)."""
    return build_user_headers(user_id, "AllocationManager")


def make_compliance_auditor_headers(user_id: str = "auditor-1") -> dict:
    """ComplianceAuditor (opaque identity)."""
    return build_user_headers(user_id, "ComplianceAuditor")


def make_agency_coordinator_headers(agency_id: str) -> dict:
    """AgencyCoordinator (entity_backed:Agency). Pass the acting Agency.id as
    X-User-ID whenever the call is ownership-gated (own order / household /
    distribution event), per PRD §2.1."""
    return build_user_headers(agency_id, "AgencyCoordinator")
