"""Identity headers for every role in the API.

Four of the five roles carry an opaque operator identifier. `ArtistRep` is the
exception: its `X-User-ID` must be the `id` of the Artist row the caller acts
for, so ownership-gated calls must always be made with
`make_artist_rep_headers(artist_id)` rather than a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ARTIST_REP,
    ROLE_BUSINESS_AFFAIRS,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PRODUCTION_MANAGER,
    ROLE_TALENT_BUYER,
)

# Opaque operator identifiers.
TALENT_BUYER_USER_ID = "buyer-001"
BUSINESS_AFFAIRS_USER_ID = "ba-001"
PRODUCTION_MANAGER_USER_ID = "pm-001"
PRODUCTION_MANAGER_2_USER_ID = "pm-002"
FINANCE_CONTROLLER_USER_ID = "fin-001"

TALENT_BUYER = build_user_headers(TALENT_BUYER_USER_ID, ROLE_TALENT_BUYER)
BUSINESS_AFFAIRS = build_user_headers(BUSINESS_AFFAIRS_USER_ID, ROLE_BUSINESS_AFFAIRS)
PRODUCTION_MANAGER = build_user_headers(
    PRODUCTION_MANAGER_USER_ID, ROLE_PRODUCTION_MANAGER
)
PRODUCTION_MANAGER_2 = build_user_headers(
    PRODUCTION_MANAGER_2_USER_ID, ROLE_PRODUCTION_MANAGER
)
FINANCE_CONTROLLER = build_user_headers(
    FINANCE_CONTROLLER_USER_ID, ROLE_FINANCE_CONTROLLER
)

TEST_USERS = {
    ROLE_TALENT_BUYER: TALENT_BUYER,
    ROLE_BUSINESS_AFFAIRS: BUSINESS_AFFAIRS,
    ROLE_PRODUCTION_MANAGER: PRODUCTION_MANAGER,
    ROLE_FINANCE_CONTROLLER: FINANCE_CONTROLLER,
}


def make_artist_rep_headers(artist_id: str) -> dict:
    """Headers for the agent of one specific act: X-User-ID is the Artist id."""
    return build_user_headers(str(artist_id), ROLE_ARTIST_REP)


def make_production_manager_headers(user_id: str) -> dict:
    """Headers for a named production manager, for segregation-of-duties tests."""
    return build_user_headers(str(user_id), ROLE_PRODUCTION_MANAGER)


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity, for authentication and role-permission checks."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
