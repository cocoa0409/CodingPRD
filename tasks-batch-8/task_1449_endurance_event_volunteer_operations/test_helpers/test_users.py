"""Pre-built role headers for every role in the PRD (PRD §2.1).

Entity-backed roles (Volunteer, Captain, GroupLeader) get a per-instance
builder: pass the real entity id whenever the call is ownership-gated.
The shared constants are safe only for calls whose success does not depend
on the caller owning the subject resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — shared constants are the canonical form
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "VolunteerCoordinator"),
    "director_headers": build_user_headers("test-director-1", "EventDirector"),
    # entity-backed roles — fallback for non-ownership tests only
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "captain_headers": build_user_headers("test-captain-1", "Captain"),
    "group_leader_headers": build_user_headers("test-group-leader-1", "GroupLeader"),
}


def make_volunteer_headers(user_id: str) -> dict:
    """For the Volunteer role (X-User-ID must be the acting Volunteer's id)."""
    return build_user_headers(user_id, "Volunteer")


def make_captain_headers(user_id: str) -> dict:
    """For the Captain role (X-User-ID must be the captain Volunteer's id)."""
    return build_user_headers(user_id, "Captain")


def make_group_leader_headers(group_id: str) -> dict:
    """For the GroupLeader role (X-User-ID must be the FundraisingGroup's id)."""
    return build_user_headers(group_id, "GroupLeader")
