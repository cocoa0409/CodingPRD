"""Pre-built role headers for every role in the PRD (§2.1).

MedicalStaffCoordinator, CredentialsCommitteeChair, MedicalExecutiveCommitteeChair,
BoardMember, and HearingOfficer are opaque identities: X-User-ID is an operator
string never compared to any entity id. DepartmentChief and Practitioner are
entity-backed by MedicalStaffMember: X-User-ID must be the acting member record's
id for ownership-gated calls (case withdraw, hearing request, grant relinquish,
case proposal). Use the per-instance builders for those.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "coordinator_headers": build_user_headers(
        "coordinator-1", "MedicalStaffCoordinator"),
    "committee_chair_headers": build_user_headers(
        "committee-chair-1", "CredentialsCommitteeChair"),
    "mec_chair_headers": build_user_headers(
        "mec-chair-1", "MedicalExecutiveCommitteeChair"),
    # The shared board identity must never collide with a MEC voter_id used in
    # fixtures, or the board segregation check would reject ratification.
    "board_member_headers": build_user_headers("board-member-1", "BoardMember"),
    "hearing_officer_headers": build_user_headers(
        "hearing-officer-1", "HearingOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g., RBAC denials before any existence check).
    "department_chief_headers": build_user_headers(
        "chief-fallback-1", "DepartmentChief"),
    "practitioner_headers": build_user_headers(
        "practitioner-fallback-1", "Practitioner"),
}


def make_coordinator_headers(user_id: str = "coordinator-1") -> dict:
    return build_user_headers(user_id, "MedicalStaffCoordinator")


def make_committee_chair_headers(user_id: str = "committee-chair-1") -> dict:
    return build_user_headers(user_id, "CredentialsCommitteeChair")


def make_mec_chair_headers(user_id: str = "mec-chair-1") -> dict:
    return build_user_headers(user_id, "MedicalExecutiveCommitteeChair")


def make_board_member_headers(user_id: str = "board-member-1") -> dict:
    """BoardMember is opaque; the SoD check compares this id string against
    the agenda item's recorded mec_voter_ids."""
    return build_user_headers(user_id, "BoardMember")


def make_hearing_officer_headers(user_id: str = "hearing-officer-1") -> dict:
    return build_user_headers(user_id, "HearingOfficer")


def make_department_chief_headers(member_id: str) -> dict:
    """For DepartmentChief (entity_backed:MedicalStaffMember). Pass the acting
    chief's MedicalStaffMember.id whenever the call is ownership-gated
    (case proposal / case withdraw)."""
    return build_user_headers(member_id, "DepartmentChief")


def make_practitioner_headers(member_id: str) -> dict:
    """For Practitioner (entity_backed:MedicalStaffMember). Pass the acting
    member's MedicalStaffMember.id whenever the call is ownership-gated
    (hearing request / grant relinquish)."""
    return build_user_headers(member_id, "Practitioner")
