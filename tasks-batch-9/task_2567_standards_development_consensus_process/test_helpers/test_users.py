"""
Role headers for the standards-development consensus API.

PRD 2.1 requires X-User-ID and X-User-Role on every request, and requires the
submitter-identity field of a write to equal X-User-ID. Four of the six roles are
backed by a Participant row, so their headers must carry the real participant id:
use the make_*_headers(participant_id) builders for those. The two operational
roles (StandardsStaff, AppealsBoard) are not participants, so a fixed opaque id
is sufficient for them.
"""

from prd_bench_local_runner.testing import build_user_headers

ROLE_PROPOSER = "Proposer"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_COMMITTEE_CHAIR = "CommitteeChair"
ROLE_PUBLIC_COMMENTER = "PublicCommenter"
ROLE_STANDARDS_STAFF = "StandardsStaff"
ROLE_APPEALS_BOARD = "AppealsBoard"

ALL_ROLES = [
    ROLE_PROPOSER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMMITTEE_CHAIR,
    ROLE_PUBLIC_COMMENTER,
    ROLE_STANDARDS_STAFF,
    ROLE_APPEALS_BOARD,
]

# Participant-backed roles: the caller's X-User-ID is a Participant id.
PARTICIPANT_BACKED_ROLES = [
    ROLE_PROPOSER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMMITTEE_CHAIR,
    ROLE_PUBLIC_COMMENTER,
]

# Opaque operational identities.
STAFF_USER_ID = "staff-secretariat-001"
APPEALS_BOARD_USER_ID = "appeals-board-001"

STAFF_HEADERS = build_user_headers(STAFF_USER_ID, ROLE_STANDARDS_STAFF)
APPEALS_BOARD_HEADERS = build_user_headers(APPEALS_BOARD_USER_ID, ROLE_APPEALS_BOARD)


def make_proposer_headers(participant_id: str) -> dict:
    """Headers for a participant acting as Proposer."""
    return build_user_headers(participant_id, ROLE_PROPOSER)


def make_member_headers(participant_id: str) -> dict:
    """Headers for a participant acting as CommitteeMember."""
    return build_user_headers(participant_id, ROLE_COMMITTEE_MEMBER)


def make_chair_headers(participant_id: str) -> dict:
    """Headers for a participant acting as CommitteeChair."""
    return build_user_headers(participant_id, ROLE_COMMITTEE_CHAIR)


def make_public_commenter_headers(participant_id: str) -> dict:
    """Headers for a participant acting as PublicCommenter."""
    return build_user_headers(participant_id, ROLE_PUBLIC_COMMENTER)


def make_staff_headers(user_id: str = STAFF_USER_ID) -> dict:
    """Headers for the secretariat; identity is opaque."""
    return build_user_headers(user_id, ROLE_STANDARDS_STAFF)


def make_appeals_board_headers(user_id: str = APPEALS_BOARD_USER_ID) -> dict:
    """Headers for the appeals panel; identity is opaque."""
    return build_user_headers(user_id, ROLE_APPEALS_BOARD)


def make_headers(participant_id: str, role: str) -> dict:
    """Headers for an arbitrary (id, role) pair — used by access-control tests."""
    return build_user_headers(participant_id, role)


def headers_without_user_id(role: str = ROLE_STANDARDS_STAFF) -> dict:
    """Headers carrying a role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(participant_id: str = STAFF_USER_ID) -> dict:
    """Headers carrying an identity but no X-User-Role at all."""
    return {"X-User-ID": participant_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = ROLE_STANDARDS_STAFF) -> dict:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(participant_id: str = STAFF_USER_ID) -> dict:
    """Headers whose X-User-Role is present but empty."""
    return {
        "X-User-ID": participant_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def no_headers() -> dict:
    """Neither authentication header."""
    return {"Content-Type": "application/json"}
