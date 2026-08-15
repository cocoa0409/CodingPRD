"""Pre-built role headers for every role in the PRD (§2.1).

The ContractorUser role is entity-backed: its X-User-ID must equal the acting
Contractor's id, so ownership-gated calls MUST use make_contractor_headers()
with the real contractor id. The shared constant is only for tests that do
not exercise ownership (e.g. malformed-payload or missing-resource checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "distributor_admin_headers": build_user_headers("test-admin-1", "DistributorAdmin"),
    "warranty_processor_headers": build_user_headers("test-processor-1", "WarrantyProcessor"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "training_coordinator_headers": build_user_headers("test-coordinator-1", "TrainingCoordinator"),
    # Entity-backed role: fallback for non-ownership tests only.
    "contractor_user_headers": build_user_headers("test-contractor-1", "ContractorUser"),
}


def make_contractor_headers(contractor_id: str) -> dict:
    """For ContractorUser (entity-backed: Contractor). Pass the actual
    Contractor.id whenever the call is ownership-gated."""
    return build_user_headers(contractor_id, "ContractorUser")
