"""Pre-built role headers for every role in the PRD (section 2.1).

All four roles use an opaque identity model: `X-User-ID` is an operator
identifier never compared to any entity id, so shared constants are the
canonical form. Builder functions exist so segregation-of-duties tests
(PRD section 3.4) can pin a specific `X-User-ID` per call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "HealthClerk"),
    "nurse_headers": build_user_headers("nurse-1", "SchoolNurse"),
    "officer_headers": build_user_headers("officer-1", "DistrictHealthOfficer"),
    "officer_2_headers": build_user_headers("officer-2", "DistrictHealthOfficer"),
    "coordinator_headers": build_user_headers("coord-1", "RegistryCoordinator"),
}


def make_clerk_headers(user_id: str) -> dict:
    """HealthClerk headers with a specific X-User-ID."""
    return build_user_headers(user_id, "HealthClerk")


def make_nurse_headers(user_id: str) -> dict:
    """SchoolNurse headers with a specific X-User-ID."""
    return build_user_headers(user_id, "SchoolNurse")


def make_officer_headers(user_id: str) -> dict:
    """DistrictHealthOfficer headers with a specific X-User-ID."""
    return build_user_headers(user_id, "DistrictHealthOfficer")


def make_coordinator_headers(user_id: str) -> dict:
    """RegistryCoordinator headers with a specific X-User-ID."""
    return build_user_headers(user_id, "RegistryCoordinator")
