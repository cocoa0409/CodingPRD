"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (FacilityCoordinator -> ContractedFacility, Technologist ->
Technologist) MUST be built through the per-instance builders whenever the call
is ownership-gated: X-User-ID must equal the backing entity's id, otherwise the
ownership check rejects the request because the id never matches a real entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for calls whose outcome does not
# depend on the caller owning the subject resource (e.g. 400-on-bad-payload or
# 404-on-missing-resource probes).
TEST_USERS = {
    "operations_director_headers": build_user_headers("test-ops-1", "OperationsDirector"),
    "reading_radiologist_headers": build_user_headers("test-reader-1", "ReadingRadiologist"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    # Fallbacks for entity-backed roles; non-ownership probes only.
    "facility_coordinator_headers": build_user_headers("test-coord-1", "FacilityCoordinator"),
    "technologist_headers": build_user_headers("test-tech-1", "Technologist"),
}


def make_facility_coordinator_headers(facility_id: str) -> dict:
    """FacilityCoordinator is entity-backed: pass the real ContractedFacility.id
    whenever the call is ownership-gated (booking, cancel, dispute)."""
    return build_user_headers(facility_id, "FacilityCoordinator")


def make_technologist_headers(technologist_id: str) -> dict:
    """Technologist is entity-backed: pass the real Technologist.id whenever the
    call is ownership-gated (scan endpoints, dose records, image transfer)."""
    return build_user_headers(technologist_id, "Technologist")


def make_operations_director_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "OperationsDirector")


def make_reading_radiologist_headers(user_id: str = "test-reader-1") -> dict:
    return build_user_headers(user_id, "ReadingRadiologist")


def make_compliance_officer_headers(user_id: str = "test-compliance-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
