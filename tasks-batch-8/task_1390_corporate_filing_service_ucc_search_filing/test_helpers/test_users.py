"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin, FilingSpecialist, FilingReviewer, FilingOfficer and SearchAnalyst
carry opaque operator identifiers — X-User-ID is never compared to a persisted
entity id — so shared constants are safe for them. ClientManager is
entity-backed: X-User-ID must equal the acting ClientAccount id on
client-scoped paths, so ownership-gated calls must use
make_client_manager_headers(client_id) with the real account id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "specialist_headers": build_user_headers("spec-1", "FilingSpecialist"),
    "specialist2_headers": build_user_headers("spec-2", "FilingSpecialist"),
    "reviewer_headers": build_user_headers("rev-1", "FilingReviewer"),
    "reviewer2_headers": build_user_headers("rev-2", "FilingReviewer"),
    "officer_headers": build_user_headers("officer-1", "FilingOfficer"),
    "analyst_headers": build_user_headers("analyst-1", "SearchAnalyst"),
    # Entity-backed role: fallback only for tests that do not exercise ownership.
    "client_manager_headers": build_user_headers("test-client-manager-1", "ClientManager"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_client_manager_headers(user_id: str) -> dict:
    """For ClientManager (entity-backed). Pass the acting ClientAccount.id whenever
    the call is ownership-gated (anything beneath /client-accounts/{id})."""
    return build_user_headers(user_id, "ClientManager")


def make_filing_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FilingSpecialist")


def make_filing_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FilingReviewer")


def make_filing_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FilingOfficer")


def make_search_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SearchAnalyst")
