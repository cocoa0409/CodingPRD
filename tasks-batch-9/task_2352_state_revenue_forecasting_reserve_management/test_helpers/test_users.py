"""Canonical operator identities and their request headers.

Every role in this API is opaque: `X-User-ID` is never compared against any
resource's `id`. It is only compared against the identity fields the PRD names
explicitly — `submitted_by_user_id` and `requested_by_user_id` for the two
segregation-of-duties rules, and `voter_user_id` for the one-ballot-per-voter
rule. Tests therefore share these constants and only vary the user id where an
identity rule is under test.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------- #
# Canonical user ids
# --------------------------------------------------------------------------- #
DIRECTOR_USER_ID = "dir-1"
DIRECTOR_ALT_USER_ID = "dir-2"
EXEC_ECONOMIST_USER_ID = "exec-eco-1"
LEG_ECONOMIST_USER_ID = "leg-eco-1"
TREASURER_USER_ID = "tr-1"
TREASURER_REQUESTER_USER_ID = "tr-req-1"
TREASURER_EXECUTOR_USER_ID = "tr-exec-9"
VOTER_USER_ID = "voter-01"
RATING_ANALYST_USER_ID = "ra-1"

VOTER_USER_IDS = [f"voter-{n:02d}" for n in range(1, 12)]


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary (user id, role) pair."""
    return build_user_headers(user_id, role)


def make_director_headers(user_id: str = DIRECTOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FORECAST_DIRECTOR.value)


def make_exec_economist_headers(user_id: str = EXEC_ECONOMIST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.EXECUTIVE_ECONOMIST.value)


def make_leg_economist_headers(user_id: str = LEG_ECONOMIST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.LEGISLATIVE_ECONOMIST.value)


def make_treasurer_headers(user_id: str = TREASURER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.RESERVE_TREASURER.value)


def make_voter_headers(user_id: str = VOTER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.LEGISLATIVE_VOTER.value)


def make_rating_analyst_headers(user_id: str = RATING_ANALYST_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.RATING_ANALYST.value)


HEADER_BUILDERS = {
    UserRole.FORECAST_DIRECTOR.value: make_director_headers,
    UserRole.EXECUTIVE_ECONOMIST.value: make_exec_economist_headers,
    UserRole.LEGISLATIVE_ECONOMIST.value: make_leg_economist_headers,
    UserRole.RESERVE_TREASURER.value: make_treasurer_headers,
    UserRole.LEGISLATIVE_VOTER.value: make_voter_headers,
    UserRole.RATING_ANALYST.value: make_rating_analyst_headers,
}


def headers_for_role(role: str) -> Dict[str, str]:
    """Default headers for a role name."""
    return HEADER_BUILDERS[role]()


# Ready-made header dicts for the common cases.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "director": make_director_headers(),
    "director_alt": make_director_headers(DIRECTOR_ALT_USER_ID),
    "exec_economist": make_exec_economist_headers(),
    "leg_economist": make_leg_economist_headers(),
    "treasurer": make_treasurer_headers(),
    "treasurer_requester": make_treasurer_headers(TREASURER_REQUESTER_USER_ID),
    "treasurer_executor": make_treasurer_headers(TREASURER_EXECUTOR_USER_ID),
    "voter": make_voter_headers(),
    "rating_analyst": make_rating_analyst_headers(),
}
