"""Pre-built role headers for every role in the PRD (§2.1).

GardenAdmin is an opaque operator identity: its X-User-ID is never compared to
any entity id. Coordinator / Volunteer / GroupLeader / FoodSafetyOfficer are
entity-backed roles: X-User-ID must be the acting Volunteer's id. Use the
make_*_headers(volunteer_id) builders whenever the call is ownership-gated or
participates in a segregation-of-duties identity comparison; the shared
constants are only for calls where no identity comparison can occur.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role: canonical form, safe everywhere (never equals a Volunteer id).
    "admin_headers": build_user_headers("test-admin-1", "GardenAdmin"),
    # Entity-backed roles: shared constants ONLY for non-ownership assertions
    # (400 shape errors, 404s, role-forbidden checks) where the identity is
    # never compared to a stored record.
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "group_leader_headers": build_user_headers("test-group-leader-1", "GroupLeader"),
    "officer_headers": build_user_headers("test-officer-1", "FoodSafetyOfficer"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """GardenAdmin (opaque identity)."""
    return build_user_headers(user_id, "GardenAdmin")


def make_coordinator_headers(user_id: str) -> dict:
    """Coordinator (entity-backed: Volunteer). Pass the acting Volunteer's id."""
    return build_user_headers(user_id, "Coordinator")


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer (entity-backed). Pass the acting Volunteer's id."""
    return build_user_headers(user_id, "Volunteer")


def make_group_leader_headers(user_id: str) -> dict:
    """GroupLeader (entity-backed). Pass the acting Volunteer's id."""
    return build_user_headers(user_id, "GroupLeader")


def make_officer_headers(user_id: str) -> dict:
    """FoodSafetyOfficer (entity-backed). Pass the acting Volunteer's id."""
    return build_user_headers(user_id, "FoodSafetyOfficer")
