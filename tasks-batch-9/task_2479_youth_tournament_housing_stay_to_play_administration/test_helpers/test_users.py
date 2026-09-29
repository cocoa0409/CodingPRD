"""Actor identities and the headers that carry them (PRD §2.1).

Identity binding is not uniform across the five roles, so this module offers two
different things.

Three roles are opaque. PRD §2.1: "When `X-User-Role` is `HousingManager`,
`ExceptionReviewer` or `RightsHolder`, `X-User-ID` is an opaque operator
identifier not tied to any persisted entity." Those get fixed constants, and
several distinct identifiers per role so segregation-of-duties tests can put two
different operators on the two halves of one decision.

Two roles are entity-backed. PRD §2.1: "When `X-User-Role` is `TeamManager`,
`X-User-ID` is the `id` of the acting `Team`" and "When `X-User-Role` is
`HotelRepresentative`, `X-User-ID` is the `id` of the acting `Hotel`." Those
cannot have fixed constants, because the identifier is a row id minted by the
server during the test; they get header *builders* instead.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------

HOUSING_MANAGER_ID = "op-housing-manager-1"
HOUSING_MANAGER_2_ID = "op-housing-manager-2"

# Two reviewers: the SoD rule on appeals needs a second pair of eyes.
EXCEPTION_REVIEWER_ID = "op-exception-reviewer-1"
EXCEPTION_REVIEWER_2_ID = "op-exception-reviewer-2"

# Two rights holders: the adjudicator-conflict and distribution-approver rules
# both need an operator who is *not* the one that made the earlier decision.
RIGHTS_HOLDER_ID = "op-rights-holder-1"
RIGHTS_HOLDER_2_ID = "op-rights-holder-2"

# An identifier that belongs to no Team and no Hotel row, for the
# ERR_ACTOR_IDENTITY_UNKNOWN pathway.
UNKNOWN_ACTOR_ID = "00000000-0000-4000-8000-0000000000ff"


# ---------------------------------------------------------------------------
# Header builders
# ---------------------------------------------------------------------------


def make_housing_manager_headers(user_id: str = HOUSING_MANAGER_ID) -> Dict[str, str]:
    """Headers for a ``HousingManager`` acting under an opaque identifier."""
    return build_user_headers(user_id, UserRole.HOUSING_MANAGER.value)


def make_exception_reviewer_headers(
    user_id: str = EXCEPTION_REVIEWER_ID,
) -> Dict[str, str]:
    """Headers for an ``ExceptionReviewer`` acting under an opaque identifier."""
    return build_user_headers(user_id, UserRole.EXCEPTION_REVIEWER.value)


def make_rights_holder_headers(user_id: str = RIGHTS_HOLDER_ID) -> Dict[str, str]:
    """Headers for a ``RightsHolder`` acting under an opaque identifier."""
    return build_user_headers(user_id, UserRole.RIGHTS_HOLDER.value)


def make_team_manager_headers(team_id: str) -> Dict[str, str]:
    """Headers for the ``TeamManager`` of the ``Team`` whose id is ``team_id``.

    PRD §2.1: "When `X-User-Role` is `TeamManager`, `X-User-ID` is the `id` of
    the acting `Team`".
    """
    return build_user_headers(team_id, UserRole.TEAM_MANAGER.value)


def make_hotel_rep_headers(hotel_id: str) -> Dict[str, str]:
    """Headers for the ``HotelRepresentative`` of the ``Hotel`` ``hotel_id``.

    PRD §2.1: "When `X-User-Role` is `HotelRepresentative`, `X-User-ID` is the
    `id` of the acting `Hotel`".
    """
    return build_user_headers(hotel_id, UserRole.HOTEL_REPRESENTATIVE.value)


# ---------------------------------------------------------------------------
# Ready-made header sets
# ---------------------------------------------------------------------------

HOUSING_MANAGER_HEADERS = make_housing_manager_headers()
HOUSING_MANAGER_2_HEADERS = make_housing_manager_headers(HOUSING_MANAGER_2_ID)
EXCEPTION_REVIEWER_HEADERS = make_exception_reviewer_headers()
EXCEPTION_REVIEWER_2_HEADERS = make_exception_reviewer_headers(EXCEPTION_REVIEWER_2_ID)
RIGHTS_HOLDER_HEADERS = make_rights_holder_headers()
RIGHTS_HOLDER_2_HEADERS = make_rights_holder_headers(RIGHTS_HOLDER_2_ID)

# An entity-backed role carrying an identifier that resolves to no row.
UNKNOWN_TEAM_MANAGER_HEADERS = make_team_manager_headers(UNKNOWN_ACTOR_ID)
UNKNOWN_HOTEL_REP_HEADERS = make_hotel_rep_headers(UNKNOWN_ACTOR_ID)

# PRD §2.1: "If either header is absent or present but empty" the request is
# rejected, so these three shapes drive the ERR_MISSING_AUTH_HEADERS pathway.
NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
MISSING_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": HOUSING_MANAGER_ID,
    "Content-Type": "application/json",
}
MISSING_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-Role": UserRole.HOUSING_MANAGER.value,
    "Content-Type": "application/json",
}
EMPTY_USER_ID_HEADERS: Dict[str, str] = {
    "X-User-ID": "",
    "X-User-Role": UserRole.HOUSING_MANAGER.value,
    "Content-Type": "application/json",
}
EMPTY_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": HOUSING_MANAGER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}

# PRD §2.1: a role value that "is not one of the five roles enumerated below".
UNKNOWN_ROLE_HEADERS: Dict[str, str] = {
    "X-User-ID": HOUSING_MANAGER_ID,
    "X-User-Role": "HousingDirector",
    "Content-Type": "application/json",
}


TEST_USERS: Dict[str, Dict[str, str]] = {
    "housing_manager_headers": HOUSING_MANAGER_HEADERS,
    "housing_manager_2_headers": HOUSING_MANAGER_2_HEADERS,
    "exception_reviewer_headers": EXCEPTION_REVIEWER_HEADERS,
    "exception_reviewer_2_headers": EXCEPTION_REVIEWER_2_HEADERS,
    "rights_holder_headers": RIGHTS_HOLDER_HEADERS,
    "rights_holder_2_headers": RIGHTS_HOLDER_2_HEADERS,
    "no_headers": NO_HEADERS,
    "missing_role_headers": MISSING_ROLE_HEADERS,
    "missing_user_id_headers": MISSING_USER_ID_HEADERS,
    "empty_user_id_headers": EMPTY_USER_ID_HEADERS,
    "empty_role_headers": EMPTY_ROLE_HEADERS,
    "unknown_role_headers": UNKNOWN_ROLE_HEADERS,
}
