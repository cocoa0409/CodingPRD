"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, admin-acted calls).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "ConferenceServicesAdmin"),
    "facilities_headers": build_user_headers("test-facilities-1", "FacilitiesManager"),
    "housekeeping_headers": build_user_headers("test-housekeeping-1", "HousekeepingSupervisor"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "screening_headers": build_user_headers("test-screening-1", "ScreeningReviewer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "coordinator_headers": build_user_headers("test-coordinator-1", "ClientCoordinator"),
}


def make_coordinator_headers(group_id: str) -> dict:
    """For ClientCoordinator (entity_backed:ConferenceGroup). Pass the actual
    ConferenceGroup.id as group_id whenever the call is ownership-gated."""
    return build_user_headers(group_id, "ClientCoordinator")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ConferenceServicesAdmin")


def make_facilities_headers(user_id: str = "test-facilities-1") -> dict:
    return build_user_headers(user_id, "FacilitiesManager")


def make_housekeeping_headers(user_id: str = "test-housekeeping-1") -> dict:
    return build_user_headers(user_id, "HousekeepingSupervisor")


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_screening_headers(user_id: str = "test-screening-1") -> dict:
    return build_user_headers(user_id, "ScreeningReviewer")
