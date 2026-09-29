"""Pre-built role headers for the seven roles of the Lateral Partner Hiring API.

``X-User-ID`` is interpreted differently by role. For ``SystemAdmin``,
``RecruitingCoordinator``, ``ConflictsCounsel``, ``CommitteeChair`` and
``CommitteeMember`` it is an opaque operator identifier, so the shared constants
below are the canonical form. For ``PracticeGroupLeader`` it is the ``id`` of the
acting PracticeGroup and for ``Candidate`` it is the ``id`` of the acting
Candidate — those two roles MUST use the per-instance builders whenever the call
is ownership-gated.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used throughout the suite.
ADMIN_USER_ID = "user-admin-1"
COORDINATOR_USER_ID = "user-coordinator-1"
COUNSEL_USER_ID = "user-counsel-1"
SPONSOR_USER_ID = "user-sponsor-1"
CHAIR_USER_ID = "user-chair-1"
PEER_CHAIR_USER_ID = "user-chair-2"
MEMBER_1_USER_ID = "user-member-1"
MEMBER_2_USER_ID = "user-member-2"
MEMBER_3_USER_ID = "user-member-3"
MEMBER_4_USER_ID = "user-member-4"
MEMBER_5_USER_ID = "user-member-5"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "system_admin_headers": build_user_headers(ADMIN_USER_ID, "SystemAdmin"),
    "recruiting_coordinator_headers": build_user_headers(
        COORDINATOR_USER_ID, "RecruitingCoordinator"
    ),
    "conflicts_counsel_headers": build_user_headers(COUNSEL_USER_ID, "ConflictsCounsel"),
    "committee_chair_headers": build_user_headers(CHAIR_USER_ID, "CommitteeChair"),
    "peer_committee_chair_headers": build_user_headers(
        PEER_CHAIR_USER_ID, "CommitteeChair"
    ),
    "committee_member_headers": build_user_headers(MEMBER_1_USER_ID, "CommitteeMember"),
    # Entity-backed roles — shared constants are a fallback for calls that are
    # NOT ownership-gated (reads, 400-on-bad-payload, 404-on-missing-resource).
    "practice_group_leader_headers": build_user_headers(
        "test-practice-group-leader-1", "PracticeGroupLeader"
    ),
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
}


# ----------------------------------------------------------------------
# Per-instance builders
# ----------------------------------------------------------------------


def make_practice_group_leader_headers(practice_group_id: str) -> dict:
    """For PracticeGroupLeader. Pass the acting PracticeGroup's ``id``."""
    return build_user_headers(practice_group_id, "PracticeGroupLeader")


def make_candidate_headers(candidate_id: str) -> dict:
    """For Candidate. Pass the acting Candidate's ``id``."""
    return build_user_headers(candidate_id, "Candidate")


def make_committee_member_headers(user_id: str) -> dict:
    """For CommitteeMember with a specific opaque ``X-User-ID``."""
    return build_user_headers(user_id, "CommitteeMember")


def make_committee_chair_headers(user_id: str) -> dict:
    """For CommitteeChair with a specific opaque ``X-User-ID``."""
    return build_user_headers(user_id, "CommitteeChair")


def make_recruiting_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RecruitingCoordinator")


def make_conflicts_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConflictsCounsel")


def make_system_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def headers_without_role(user_id: str = ADMIN_USER_ID) -> dict:
    """Well-formed request that omits ``X-User-Role`` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "SystemAdmin") -> dict:
    """Well-formed request that omits ``X-User-ID`` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = ADMIN_USER_ID) -> dict:
    """Both headers present but the role is not one of the seven declared names."""
    return build_user_headers(user_id, "OfficeManager")
