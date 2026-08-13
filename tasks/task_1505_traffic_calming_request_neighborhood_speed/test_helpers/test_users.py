"""Pre-built role headers for every role in the PRD (§2.1).

`Resident` is entity-backed: X-User-ID must be the id of a registered
Resident record whenever the call is ownership- or household-gated, so
fixtures MUST use make_resident_headers(resident["id"]) for those calls.
The shared constant is a fallback for non-ownership tests only.

The other four roles are opaque: X-User-ID is an operator identifier never
compared to an entity id (though it may be recorded, e.g. as a plan's
created_by_user_id), so shared constants are their canonical form; builders
exist to pin a specific operator id (e.g. segregation-of-duties tests).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity-backed role: fallback for non-ownership tests only.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    # opaque roles: canonical shared form.
    "traffic_engineer_headers": build_user_headers("te-1", "TrafficEngineer"),
    "city_engineer_headers": build_user_headers("ce-1", "CityEngineer"),
    "emergency_reviewer_headers": build_user_headers("er-1", "EmergencyReviewer"),
    "city_admin_headers": build_user_headers("admin-1", "CityAdmin"),
}


def make_resident_headers(user_id: str) -> dict:
    """Resident is entity-backed: pass the actual Resident.id whenever the
    call is ownership- or household-gated."""
    return build_user_headers(user_id, "Resident")


def make_traffic_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TrafficEngineer")


def make_city_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CityEngineer")


def make_emergency_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EmergencyReviewer")


def make_city_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CityAdmin")
