"""Pre-built role headers for every role in the PRD (§2.1).

All five roles use opaque operator identifiers: `X-User-ID` is never compared
to any entity's id for ownership. The single place the user id matters is the
report-review segregation-of-duties check, which compares the reviewer's
`X-User-ID` against the report's stored `submitted_by_user_id`; tests
exercising it use the per-role builders with explicit user ids.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "case_manager_headers": build_user_headers("cm-1", "CaseManager"),
    "housing_coordinator_headers": build_user_headers("hc-1", "HousingCoordinator"),
    "employment_specialist_headers": build_user_headers("es-1", "EmploymentSpecialist"),
    "agency_director_headers": build_user_headers("dir-1", "AgencyDirector"),
    "federal_officer_headers": build_user_headers("off-1", "FederalOfficer"),
}


def make_case_manager_headers(user_id: str) -> dict:
    """CaseManager headers with an explicit opaque user id."""
    return build_user_headers(user_id, "CaseManager")


def make_housing_coordinator_headers(user_id: str) -> dict:
    """HousingCoordinator headers with an explicit opaque user id."""
    return build_user_headers(user_id, "HousingCoordinator")


def make_employment_specialist_headers(user_id: str) -> dict:
    """EmploymentSpecialist headers with an explicit opaque user id."""
    return build_user_headers(user_id, "EmploymentSpecialist")


def make_agency_director_headers(user_id: str) -> dict:
    """AgencyDirector headers with an explicit opaque user id; the id is
    recorded as submitted_by_user_id on report submission (PRD §3.7)."""
    return build_user_headers(user_id, "AgencyDirector")


def make_federal_officer_headers(user_id: str) -> dict:
    """FederalOfficer headers with an explicit opaque user id; the id is
    compared against submitted_by_user_id by the segregation-of-duties rule
    on report review (PRD §3.7)."""
    return build_user_headers(user_id, "FederalOfficer")
