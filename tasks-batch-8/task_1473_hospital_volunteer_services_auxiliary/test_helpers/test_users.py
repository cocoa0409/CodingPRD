"""Pre-built role headers for every role in the PRD.

X-User-ID semantics (PRD §2.1): for VolunteerServicesDirector, VolunteerCoordinator,
Screener, DepartmentHead, and AuxiliaryTreasurer the id is an opaque operator id; for
Volunteer the id IS the acting volunteer record's id, so ownership-gated calls must
use make_volunteer_headers(volunteer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    "director_headers": build_user_headers("director-1", "VolunteerServicesDirector"),
    "coordinator_headers": build_user_headers("coordinator-1", "VolunteerCoordinator"),
    "screener_headers": build_user_headers("screener-1", "Screener"),
    "screener2_headers": build_user_headers("screener-2", "Screener"),
    "treasurer_headers": build_user_headers("treasurer-1", "AuxiliaryTreasurer"),
    "treasurer2_headers": build_user_headers("treasurer-2", "AuxiliaryTreasurer"),
    "dept_head_headers": build_user_headers("dh-1", "DepartmentHead"),
    "dept_head2_headers": build_user_headers("dh-2", "DepartmentHead"),
    # Fallback only — ownership-gated volunteer calls MUST use make_volunteer_headers.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
}


def make_director_headers(user_id: str = "director-1") -> dict:
    return build_user_headers(user_id, "VolunteerServicesDirector")


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    return build_user_headers(user_id, "VolunteerCoordinator")


def make_screener_headers(user_id: str) -> dict:
    """Screener operator id (opaque). Use distinct ids to satisfy adjudication SoD."""
    return build_user_headers(user_id, "Screener")


def make_department_head_headers(user_id: str) -> dict:
    """DepartmentHead — ownership compares Department.head_user_id to X-User-ID."""
    return build_user_headers(user_id, "DepartmentHead")


def make_treasurer_headers(user_id: str) -> dict:
    """Treasurer operator id (opaque). Disbursement SoD: disburser != campaign creator."""
    return build_user_headers(user_id, "AuxiliaryTreasurer")


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer (entity_backed:Volunteer). Pass the actual Volunteer.id whenever the
    call is ownership-gated (self-read, self-signup, own placements, own hours)."""
    return build_user_headers(user_id, "Volunteer")
