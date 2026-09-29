"""Pre-built auth headers for the seven roles.

The five opaque roles get named operator identifiers, because two decisions in
this system are split on X-User-ID rather than on X-User-Role and therefore need
two distinct users of the same role. The two entity-backed roles get builders
instead of constants: their X-User-ID must be the id of the acting member or
volunteer record, so a shared constant could never pass an ownership check.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- Opaque operator identifiers -------------------------------------------
CORPS_DIRECTOR_ID = "cd-dana"
MEMBERSHIP_COORDINATOR_ID = "mc-mira"
TOUR_MANAGER_ID = "tm-quinn"
BUSINESS_MANAGER_ID = "bm-anna"
SECOND_BUSINESS_MANAGER_ID = "bm-brett"
VOLUNTEER_SCREENER_ID = "scr-remy"
SECOND_VOLUNTEER_SCREENER_ID = "scr-sasha"


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user identifier acting in an arbitrary role."""
    return build_user_headers(user_id, role)


CORPS_DIRECTOR_HEADERS = make_headers(CORPS_DIRECTOR_ID, Role.CORPS_DIRECTOR)
MEMBERSHIP_COORDINATOR_HEADERS = make_headers(
    MEMBERSHIP_COORDINATOR_ID, Role.MEMBERSHIP_COORDINATOR
)
TOUR_MANAGER_HEADERS = make_headers(TOUR_MANAGER_ID, Role.TOUR_MANAGER)
BUSINESS_MANAGER_HEADERS = make_headers(BUSINESS_MANAGER_ID, Role.BUSINESS_MANAGER)
SECOND_BUSINESS_MANAGER_HEADERS = make_headers(
    SECOND_BUSINESS_MANAGER_ID, Role.BUSINESS_MANAGER
)
VOLUNTEER_SCREENER_HEADERS = make_headers(
    VOLUNTEER_SCREENER_ID, Role.VOLUNTEER_SCREENER
)
SECOND_VOLUNTEER_SCREENER_HEADERS = make_headers(
    SECOND_VOLUNTEER_SCREENER_ID, Role.VOLUNTEER_SCREENER
)

# The screener acting in the tour-manager capacity: same X-User-ID, different
# X-User-Role. Used to show that the duties split keys on the identifier.
SCREENER_AS_TOUR_MANAGER_HEADERS = make_headers(
    VOLUNTEER_SCREENER_ID, Role.TOUR_MANAGER
)


def make_member_headers(member_id: str) -> Dict[str, str]:
    """Headers for the member whose record id is member_id."""
    return make_headers(member_id, Role.MEMBER)


def make_volunteer_headers(volunteer_id: str) -> Dict[str, str]:
    """Headers for the volunteer whose record id is volunteer_id."""
    return make_headers(volunteer_id, Role.VOLUNTEER)


def make_business_manager_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.BUSINESS_MANAGER)


def make_screener_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.VOLUNTEER_SCREENER)


def make_tour_manager_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.TOUR_MANAGER)


# --- Malformed auth headers -------------------------------------------------
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": Role.CORPS_DIRECTOR,
    "Content-Type": "application/json",
}

MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": CORPS_DIRECTOR_ID,
    "Content-Type": "application/json",
}


def unknown_role_headers(role: str = "SeasonIntern") -> Dict[str, str]:
    """Headers carrying a role string outside the declared set of seven."""
    return {
        "X-User-ID": CORPS_DIRECTOR_ID,
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


# Headers keyed by role name, for tests that sweep the authorization column.
HEADERS_BY_ROLE = {
    Role.CORPS_DIRECTOR: CORPS_DIRECTOR_HEADERS,
    Role.MEMBERSHIP_COORDINATOR: MEMBERSHIP_COORDINATOR_HEADERS,
    Role.TOUR_MANAGER: TOUR_MANAGER_HEADERS,
    Role.BUSINESS_MANAGER: BUSINESS_MANAGER_HEADERS,
    Role.VOLUNTEER_SCREENER: VOLUNTEER_SCREENER_HEADERS,
}

TEST_USERS = {
    "corps_director_headers": CORPS_DIRECTOR_HEADERS,
    "membership_coordinator_headers": MEMBERSHIP_COORDINATOR_HEADERS,
    "tour_manager_headers": TOUR_MANAGER_HEADERS,
    "business_manager_headers": BUSINESS_MANAGER_HEADERS,
    "second_business_manager_headers": SECOND_BUSINESS_MANAGER_HEADERS,
    "volunteer_screener_headers": VOLUNTEER_SCREENER_HEADERS,
    "second_volunteer_screener_headers": SECOND_VOLUNTEER_SCREENER_HEADERS,
    "screener_as_tour_manager_headers": SCREENER_AS_TOUR_MANAGER_HEADERS,
    "no_auth_headers": NO_AUTH_HEADERS,
}
