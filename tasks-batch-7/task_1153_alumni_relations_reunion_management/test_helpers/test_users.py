"""Pre-built role headers for every role in the PRD (§2.1).

`AlumniRelationsStaff` and `AlumniRelationsDirector` are opaque roles: the
server does not compare `X-User-ID` to any entity's `id`, so shared constants
are canonical for them.

`ReunionChair`, `CommitteeVolunteer`, `AffinityGroupLeader`, and `Alumni` are
entity-backed by the alumnus record: `X-User-ID` must be the acting
`AlumniRecord.id`. Always build their headers with the per-instance builders
below, passing the actual record id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "staff_headers": build_user_headers("test-staff-1", "AlumniRelationsStaff"),
    "director_headers": build_user_headers("test-director-1", "AlumniRelationsDirector"),
    # Entity-backed roles — fallback ONLY for tests that never exercise
    # ownership (e.g. role-denial probes where the call must be rejected
    # before any ownership comparison matters).
    "reunion_chair_headers": build_user_headers("test-chair-1", "ReunionChair"),
    "committee_volunteer_headers": build_user_headers("test-volunteer-1", "CommitteeVolunteer"),
    "affinity_group_leader_headers": build_user_headers("test-leader-1", "AffinityGroupLeader"),
    "alumni_headers": build_user_headers("test-alumni-1", "Alumni"),
}


def make_reunion_chair_headers(user_id: str) -> dict:
    """ReunionChair is entity-backed: pass the acting AlumniRecord.id."""
    return build_user_headers(user_id, "ReunionChair")


def make_committee_volunteer_headers(user_id: str) -> dict:
    """CommitteeVolunteer is entity-backed: pass the acting AlumniRecord.id."""
    return build_user_headers(user_id, "CommitteeVolunteer")


def make_affinity_group_leader_headers(user_id: str) -> dict:
    """AffinityGroupLeader is entity-backed: pass the acting AlumniRecord.id."""
    return build_user_headers(user_id, "AffinityGroupLeader")


def make_alumni_headers(user_id: str) -> dict:
    """Alumni is entity-backed: pass the acting AlumniRecord.id."""
    return build_user_headers(user_id, "Alumni")
