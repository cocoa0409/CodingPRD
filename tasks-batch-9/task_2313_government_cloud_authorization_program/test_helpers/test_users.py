"""Acting identities and request headers (PRD 2.1).

Three of the four roles carry an opaque operator identifier in ``X-User-ID``.
The fourth, ``AgencyAuthorizingOfficial``, carries the ``id`` of a real
``Agency`` row, so its headers can only be built once that row exists — hence
``make_agency_official_headers(agency_id)`` rather than a module-level constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_AGENCY_OFFICIAL,
    ROLE_ASSESSOR,
    ROLE_BOARD_REVIEWER,
    ROLE_CSP_LEAD,
)

# ---------------------------------------------------------------------------
# Opaque operator identifiers
# ---------------------------------------------------------------------------

CSP_LEAD_1 = "csp-lead-1"
CSP_LEAD_2 = "csp-lead-2"

ASSESSOR_1 = "3pao-1"
ASSESSOR_2 = "3pao-2"

#: Two distinct board members are required wherever segregation of duties
#: applies: the router may not be the decider and the reviewer may not be the
#: authorizer (PRD 2.8).
BOARD_1 = "board-1"
BOARD_2 = "board-2"


# ---------------------------------------------------------------------------
# Header builders
# ---------------------------------------------------------------------------


def make_csp_lead_headers(user_id: str = CSP_LEAD_1) -> dict:
    """Headers for a ``CspComplianceLead`` acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_CSP_LEAD)


def make_assessor_headers(user_id: str = ASSESSOR_1) -> dict:
    """Headers for a ``ThirdPartyAssessor`` acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_ASSESSOR)


def make_board_headers(user_id: str = BOARD_1) -> dict:
    """Headers for a ``ProgramBoardReviewer`` acting under an opaque operator id."""
    return build_user_headers(user_id, ROLE_BOARD_REVIEWER)


def make_agency_official_headers(agency_id: str) -> dict:
    """Headers for an ``AgencyAuthorizingOfficial``.

    ``X-User-ID`` is the ``id`` of the acting ``Agency``, so the caller must
    pass the identifier of a persisted agency row.
    """
    return build_user_headers(agency_id, ROLE_AGENCY_OFFICIAL)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user/role pair."""
    return build_user_headers(user_id, role)


# ---------------------------------------------------------------------------
# Pre-built header dicts for the three opaque roles
# ---------------------------------------------------------------------------

CSP_LEAD_HEADERS = make_csp_lead_headers(CSP_LEAD_1)
CSP_LEAD_2_HEADERS = make_csp_lead_headers(CSP_LEAD_2)
ASSESSOR_HEADERS = make_assessor_headers(ASSESSOR_1)
ASSESSOR_2_HEADERS = make_assessor_headers(ASSESSOR_2)
BOARD_HEADERS = make_board_headers(BOARD_1)
BOARD_2_HEADERS = make_board_headers(BOARD_2)


# ---------------------------------------------------------------------------
# Malformed identities for authentication tests
# ---------------------------------------------------------------------------

#: Both headers absent.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}

#: ``X-User-Role`` present but not one of the four recognized roles.
UNKNOWN_ROLE_HEADERS = build_user_headers(CSP_LEAD_1, "SecurityOfficer")

#: ``X-User-ID`` absent while the role is legal.
MISSING_USER_ID_HEADERS = {
    "X-User-Role": ROLE_CSP_LEAD,
    "Content-Type": "application/json",
}

#: ``X-User-Role`` absent while the user id is present.
MISSING_ROLE_HEADERS = {
    "X-User-ID": CSP_LEAD_1,
    "Content-Type": "application/json",
}
