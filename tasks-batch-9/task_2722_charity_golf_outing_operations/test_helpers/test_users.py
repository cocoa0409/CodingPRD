"""Pre-built identity headers for every role of the access-control matrix.

Four of the six roles carry an opaque staff operator identifier that the server
never resolves to a row; the ``Participant`` role is entity-backed, so its
``X-User-ID`` must be the id of the acting ``Player`` row.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BENEFICIARY,
    ROLE_CHARITY_TREASURER,
    ROLE_COURSE_OPERATIONS,
    ROLE_PARTICIPANT,
    ROLE_SPONSORSHIP_MANAGER,
    ROLE_TOURNAMENT_DIRECTOR,
)

# --- opaque staff operator identifiers ----------------------------------
DIRECTOR_USER_ID = "user-director-001"
DIRECTOR_ALT_USER_ID = "user-director-002"
SPONSORSHIP_USER_ID = "user-sponsorship-001"
SPONSORSHIP_ALT_USER_ID = "user-sponsorship-002"
TREASURER_USER_ID = "user-treasurer-001"
TREASURER_ALT_USER_ID = "user-treasurer-002"
COURSE_USER_ID = "user-course-001"
COURSE_ALT_USER_ID = "user-course-002"
BENEFICIARY_USER_ID = "user-beneficiary-001"

# --- ready-made header bundles ------------------------------------------
DIRECTOR_HEADERS = build_user_headers(DIRECTOR_USER_ID, ROLE_TOURNAMENT_DIRECTOR)
DIRECTOR_ALT_HEADERS = build_user_headers(DIRECTOR_ALT_USER_ID, ROLE_TOURNAMENT_DIRECTOR)
SPONSORSHIP_HEADERS = build_user_headers(SPONSORSHIP_USER_ID, ROLE_SPONSORSHIP_MANAGER)
SPONSORSHIP_ALT_HEADERS = build_user_headers(SPONSORSHIP_ALT_USER_ID, ROLE_SPONSORSHIP_MANAGER)
TREASURER_HEADERS = build_user_headers(TREASURER_USER_ID, ROLE_CHARITY_TREASURER)
TREASURER_ALT_HEADERS = build_user_headers(TREASURER_ALT_USER_ID, ROLE_CHARITY_TREASURER)
COURSE_HEADERS = build_user_headers(COURSE_USER_ID, ROLE_COURSE_OPERATIONS)
COURSE_ALT_HEADERS = build_user_headers(COURSE_ALT_USER_ID, ROLE_COURSE_OPERATIONS)
BENEFICIARY_HEADERS = build_user_headers(BENEFICIARY_USER_ID, ROLE_BENEFICIARY)

ROLE_HEADERS = {
    ROLE_TOURNAMENT_DIRECTOR: DIRECTOR_HEADERS,
    ROLE_SPONSORSHIP_MANAGER: SPONSORSHIP_HEADERS,
    ROLE_CHARITY_TREASURER: TREASURER_HEADERS,
    ROLE_COURSE_OPERATIONS: COURSE_HEADERS,
    ROLE_BENEFICIARY: BENEFICIARY_HEADERS,
}


def make_participant_headers(player_id: str) -> Dict[str, str]:
    """Identity headers for the entity-backed ``Participant`` role."""
    return build_user_headers(player_id, ROLE_PARTICIPANT)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary identity, for segregation-of-duties scenarios."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, player_id: Optional[str] = None) -> Dict[str, str]:
    """Return a usable header bundle for any of the six declared roles."""
    if role == ROLE_PARTICIPANT:
        if player_id is None:
            raise ValueError("the Participant role needs the acting player's id")
        return make_participant_headers(player_id)
    return ROLE_HEADERS[role]


# --- identity headers that fail the very first check --------------------
NO_HEADERS: Dict[str, str] = {}
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_TOURNAMENT_DIRECTOR,
    "Content-Type": "application/json",
}
MISSING_ROLE_HEADERS = {
    "X-User-ID": DIRECTOR_USER_ID,
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": DIRECTOR_USER_ID,
    "X-User-Role": "GreensKeeper",
    "Content-Type": "application/json",
}
