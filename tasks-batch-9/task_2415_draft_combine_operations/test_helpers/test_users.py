"""Auth headers for the six roles.

Three roles are entity backed: ``ClubGM`` and ``ClubMedicalDirector`` act as a
``Club`` id, and ``ProspectAgent`` acts as a ``Prospect`` id. Any call that is
ownership gated must therefore be issued with headers built from the real
entity id via ``make_club_gm_headers`` / ``make_club_medical_director_headers``
/ ``make_prospect_agent_headers``. The other three roles carry opaque operator
identifiers that the server never compares to an entity id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------

LEAGUE_ADMIN_USER_ID = "admin-user-1"
EXAMINER_USER_ID = "examiner-user-1"
COMMITTEE_USER_ID = "committee-user-1"
SECOND_COMMITTEE_USER_ID = "committee-user-2"

# Alternate committee/examiner identifiers used where a test needs a second,
# clearly distinguishable operator.
COMMITTEE_REVIEWER_USER_ID = "U-COMM-1"
COMMITTEE_DECIDER_USER_ID = "U-COMM-2"
EXAMINER_ALT_USER_ID = "U-EXAM-1"

# Placeholder identifiers for the entity-backed roles. Only usable where no
# ownership comparison happens; ownership-gated calls must thread a real id.
PLACEHOLDER_CLUB_ID = "club-placeholder-1"
PLACEHOLDER_PROSPECT_ID = "prospect-placeholder-1"


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Build headers for an arbitrary user identifier and role."""
    return build_user_headers(user_id, role)


def make_league_admin_headers(
    user_id: str = LEAGUE_ADMIN_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, "LeagueDraftAdmin")


def make_examiner_headers(user_id: str = EXAMINER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "CombineMedicalExaminer")


def make_committee_headers(user_id: str = COMMITTEE_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "EligibilityCommittee")


def make_club_gm_headers(club_id: str) -> Dict[str, str]:
    """Headers for the general manager of the club with this id."""
    return build_user_headers(club_id, "ClubGM")


def make_club_medical_director_headers(club_id: str) -> Dict[str, str]:
    """Headers for the medical director of the club with this id."""
    return build_user_headers(club_id, "ClubMedicalDirector")


def make_prospect_agent_headers(prospect_id: str) -> Dict[str, str]:
    """Headers for the agent representing the prospect with this id."""
    return build_user_headers(prospect_id, "ProspectAgent")


# Convenience map of role name -> ready-made headers. Entity-backed entries use
# placeholder identifiers and must not be used for ownership-gated calls.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "LeagueDraftAdmin": make_league_admin_headers(),
    "CombineMedicalExaminer": make_examiner_headers(),
    "EligibilityCommittee": make_committee_headers(),
    "ClubGM": make_club_gm_headers(PLACEHOLDER_CLUB_ID),
    "ClubMedicalDirector": make_club_medical_director_headers(
        PLACEHOLDER_CLUB_ID
    ),
    "ProspectAgent": make_prospect_agent_headers(PLACEHOLDER_PROSPECT_ID),
}

ALL_ROLES = list(TEST_USERS.keys())
