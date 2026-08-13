"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ProgramCoordinator, FoodSafetyOfficer, GrantReviewer) use shared
constants. Entity-backed roles (CrewLeader, Volunteer) additionally get
per-instance builders: ownership checks compare X-User-ID against the acting
Volunteer's id, so callers must pass the real volunteer id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — the canonical form.
    "coordinator_headers": build_user_headers("test-coordinator-1", "ProgramCoordinator"),
    "officer_headers": build_user_headers("test-officer-1", "FoodSafetyOfficer"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "GrantReviewer"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "crew_leader_headers": build_user_headers("test-crew-leader-1", "CrewLeader"),
}


def make_volunteer_headers(user_id: str) -> dict:
    """Volunteer is entity-backed: X-User-ID must be the acting Volunteer's id."""
    return build_user_headers(user_id, "Volunteer")


def make_crew_leader_headers(user_id: str) -> dict:
    """CrewLeader is entity-backed: X-User-ID must be the acting Volunteer's id."""
    return build_user_headers(user_id, "CrewLeader")
