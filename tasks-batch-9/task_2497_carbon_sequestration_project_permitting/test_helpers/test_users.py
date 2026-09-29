"""Pre-built role headers for every role in the PRD.

All five roles use an opaque identity model, so the shared constants below are
the canonical form for each role. One value is nevertheless compared by the
server: a tract stores the opaque identifier of the landowner entitled to
negotiate it, and a landowner responding to an offer must present an
`X-User-ID` equal to that stored value. `make_landowner_headers` exists so a
fixture that registered a tract for a particular landowner identifier can act
as exactly that landowner.
"""

from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-1"
DEVELOPER_USER_ID = "developer-1"
REVIEWER_USER_ID = "reviewer-1"
SECOND_REVIEWER_USER_ID = "reviewer-2"
OTHER_REVIEWER_USER_ID = "reviewer-9"
VERIFIER_USER_ID = "verifier-1"
LANDOWNER_1_USER_ID = "landowner-1"
LANDOWNER_2_USER_ID = "landowner-2"
LANDOWNER_3_USER_ID = "landowner-3"
STRANGER_LANDOWNER_USER_ID = "landowner-9"


TEST_USERS = {
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "project_developer_headers": build_user_headers(
        DEVELOPER_USER_ID, "ProjectDeveloper"
    ),
    "regulatory_reviewer_headers": build_user_headers(
        REVIEWER_USER_ID, "RegulatoryReviewer"
    ),
    "second_reviewer_headers": build_user_headers(
        SECOND_REVIEWER_USER_ID, "RegulatoryReviewer"
    ),
    "other_reviewer_headers": build_user_headers(
        OTHER_REVIEWER_USER_ID, "RegulatoryReviewer"
    ),
    "independent_verifier_headers": build_user_headers(
        VERIFIER_USER_ID, "IndependentVerifier"
    ),
    "landowner_headers": build_user_headers(LANDOWNER_1_USER_ID, "Landowner"),
    "second_landowner_headers": build_user_headers(LANDOWNER_2_USER_ID, "Landowner"),
    "third_landowner_headers": build_user_headers(LANDOWNER_3_USER_ID, "Landowner"),
    "stranger_landowner_headers": build_user_headers(
        STRANGER_LANDOWNER_USER_ID, "Landowner"
    ),
}


def make_program_admin_headers(user_id: str) -> dict:
    """Headers for a `ProgramAdmin` acting under the supplied opaque identifier."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_project_developer_headers(user_id: str) -> dict:
    """Headers for a `ProjectDeveloper` acting under the supplied opaque identifier.

    The server records this identifier as `submitted_by_user_id` on a claim at
    submission, so claim-verification tests need to control it.
    """
    return build_user_headers(user_id, "ProjectDeveloper")


def make_regulatory_reviewer_headers(user_id: str) -> dict:
    """Headers for a `RegulatoryReviewer` acting under the supplied opaque identifier.

    The server records this identifier as `reviewer_user_id`,
    `technical_reviewer_user_id`, `approved_by_user_id`,
    `waiver_reviewer_user_id` or `closure_certified_by_user_id` depending on the
    transition, so segregation-of-duties tests need to control it.
    """
    return build_user_headers(user_id, "RegulatoryReviewer")


def make_independent_verifier_headers(user_id: str) -> dict:
    """Headers for an `IndependentVerifier` acting under the supplied identifier."""
    return build_user_headers(user_id, "IndependentVerifier")


def make_landowner_headers(user_id: str) -> dict:
    """Headers for a `Landowner`.

    Pass the tract's stored `landowner_user_id` whenever the call responds to an
    outstanding offer on that tract.
    """
    return build_user_headers(user_id, "Landowner")
