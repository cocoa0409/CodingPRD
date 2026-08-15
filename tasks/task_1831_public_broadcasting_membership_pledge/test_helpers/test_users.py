"""Pre-built role headers for the three roles in the PRD.

All three roles have `identity: opaque` (PRD §2.1): X-User-ID is an opaque
operator identifier not tied to any persisted entity, so the shared constants
below are canonical. The make_*_headers builders exist for tests that need a
specific X-User-ID string (e.g. the NFFS segregation-of-duties checks, where
the finalizer's X-User-ID is compared to the report's drafted_by_user_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "station_admin_headers": build_user_headers("test-admin-1", "StationAdmin"),
    "coordinator_headers": build_user_headers("test-coord-1", "MembershipCoordinator"),
    "phone_volunteer_headers": build_user_headers("test-volunteer-1", "PhoneVolunteer"),
}


def make_station_admin_headers(user_id: str) -> dict:
    """StationAdmin headers carrying a specific opaque X-User-ID."""
    return build_user_headers(user_id, "StationAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    """MembershipCoordinator headers carrying a specific opaque X-User-ID."""
    return build_user_headers(user_id, "MembershipCoordinator")


def make_phone_volunteer_headers(user_id: str) -> dict:
    """PhoneVolunteer headers carrying a specific opaque X-User-ID."""
    return build_user_headers(user_id, "PhoneVolunteer")
