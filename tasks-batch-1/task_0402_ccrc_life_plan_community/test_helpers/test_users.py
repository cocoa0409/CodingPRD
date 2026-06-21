"""Pre-built role headers for every role in the PRD (PRD §2.1).

Per PRD §2.1:
  * FinanceOfficer, AdmissionsDirector, and CareCoordinator are opaque operator
    identifiers — X-User-ID is not tied to any persisted entity and the server
    does not compare it to any entity's id. Shared constants suffice.
  * Resident is entity_backed:Resident. When X-User-Role is Resident, X-User-ID
    is the id of the acting Resident, and ownership checks on any resource that
    references a Resident compare the resource's foreign-key field to X-User-ID.
    Resident-acting calls (casting a council vote) therefore use
    make_resident_headers(resident_id) with the actual Resident.id.

The shared TEST_USERS["resident_headers"] constant is a fallback usable only by
tests that do NOT exercise resident ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS: dict = {
    # Three opaque roles — shared constants are safe for all calls.
    "finance_officer_headers": build_user_headers(
        "test-finance-officer-1", "FinanceOfficer",
    ),
    "admissions_director_headers": build_user_headers(
        "test-admissions-director-1", "AdmissionsDirector",
    ),
    "care_coordinator_headers": build_user_headers(
        "test-care-coordinator-1", "CareCoordinator",
    ),
    # Resident shared constant — ONLY for non-ownership / negative tests.
    "resident_headers": build_user_headers(
        "test-resident-1", "Resident",
    ),
}


def make_finance_officer_headers(opaque_id: str = "test-finance-officer-1") -> dict:
    return build_user_headers(opaque_id, "FinanceOfficer")


def make_admissions_director_headers(
    opaque_id: str = "test-admissions-director-1",
) -> dict:
    return build_user_headers(opaque_id, "AdmissionsDirector")


def make_care_coordinator_headers(
    opaque_id: str = "test-care-coordinator-1",
) -> dict:
    return build_user_headers(opaque_id, "CareCoordinator")


def make_resident_headers(resident_id: str) -> dict:
    """For Resident (entity_backed:Resident). Pass the actual Resident.id as
    user_id whenever the call is ownership-gated (PRD §2.1) — e.g. casting a
    council vote on behalf of one's own residency."""
    return build_user_headers(resident_id, "Resident")
