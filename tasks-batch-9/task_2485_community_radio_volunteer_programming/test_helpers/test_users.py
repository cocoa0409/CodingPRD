"""Pre-built role headers for every role named in the PRD (§2.1).

Two of the six roles carry an identity that the server compares against a
persisted roster row: when `X-User-Role` is `Volunteer` or `CommitteeMember`,
`X-User-ID` is the `id` of the acting `Volunteer` row. Every ownership-gated
call for those two roles MUST therefore use the per-instance builders below,
passing the real volunteer id. The remaining four roles are opaque operator
identities that the server never compares to any row's id, so the shared
constants are the canonical form for them.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities used by the recipes in this suite. The compliance
# officer identity matters twice over: it is recorded as `reviewed_by_user_id`
# on a spot and as `adjudicated_by_user_id` on an incident, which is what makes
# the segregation-of-duties comparison possible.
OFFICER_ONE = "officer-1"
OFFICER_TWO = "officer-2"
OFFICER_ADJUDICATOR = "officer-adjudicator"
OFFICER_COPY_DESK = "officer-copy-desk"
OFFICER_LOGS = "officer-logs"
OFFICER_SWEEPER = "officer-sweeper"

DIRECTOR_ONE = "director-1"
TRAINER_ONE = "trainer-1"
DEVELOPMENT_ONE = "development-1"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "program_director_headers": build_user_headers(DIRECTOR_ONE, "ProgramDirector"),
    "compliance_officer_headers": build_user_headers(OFFICER_ONE, "ComplianceOfficer"),
    "training_coordinator_headers": build_user_headers(TRAINER_ONE, "TrainingCoordinator"),
    "development_coordinator_headers": build_user_headers(
        DEVELOPMENT_ONE, "DevelopmentCoordinator"
    ),
    # Roster-backed roles — these shared constants are a fallback for calls that
    # exercise no ownership check at all (bad payloads, missing resources).
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "committee_member_headers": build_user_headers("test-committee-member-1", "CommitteeMember"),
}


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Headers for the `Volunteer` role. `volunteer_id` must be the acting
    volunteer's own `id`, because ownership checks compare a resource's
    volunteer-bearing field against `X-User-ID`."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_committee_member_headers(volunteer_id: str) -> dict:
    """Headers for the `CommitteeMember` role. `volunteer_id` must be the `id`
    of the acting `Volunteer` row, one whose `committee_seat` is true."""
    return build_user_headers(volunteer_id, "CommitteeMember")


def make_program_director_headers(user_id: str = DIRECTOR_ONE) -> dict:
    """Headers for the `ProgramDirector` role (opaque operator identity)."""
    return build_user_headers(user_id, "ProgramDirector")


def make_compliance_officer_headers(user_id: str = OFFICER_ONE) -> dict:
    """Headers for the `ComplianceOfficer` role. The supplied identity is what
    the server records as `reviewed_by_user_id` / `adjudicated_by_user_id`."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_training_coordinator_headers(user_id: str = TRAINER_ONE) -> dict:
    """Headers for the `TrainingCoordinator` role (opaque operator identity)."""
    return build_user_headers(user_id, "TrainingCoordinator")


def make_development_coordinator_headers(user_id: str = DEVELOPMENT_ONE) -> dict:
    """Headers for the `DevelopmentCoordinator` role (opaque operator identity)."""
    return build_user_headers(user_id, "DevelopmentCoordinator")


# Convenience aliases for the most frequently used operator headers.
DIRECTOR_HEADERS = TEST_USERS["program_director_headers"]
OFFICER_HEADERS = TEST_USERS["compliance_officer_headers"]
TRAINER_HEADERS = TEST_USERS["training_coordinator_headers"]
DEVELOPMENT_HEADERS = TEST_USERS["development_coordinator_headers"]
