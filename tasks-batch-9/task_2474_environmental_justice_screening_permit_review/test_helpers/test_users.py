"""Caller identities used by the test suite.

PRD §2.1 declares eight roles. Seven of them are *opaque*: the API never
resolves `X-User-ID` against a stored row, so any stable string works.
`ApplicantRepresentative` is the single exception -- it is entity-backed by a
facility, so its `X-User-ID` must be the facility's `id`. Ownership-gated
application calls therefore MUST use `make_applicant_headers(facility_id)`
rather than any shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPLICANT_REPRESENTATIVE,
    ROLE_COMMUNITY_LIAISON,
    ROLE_EJ_ANALYST,
    ROLE_INSPECTOR,
    ROLE_PERMIT_MANAGER,
    ROLE_PROGRAM_ADMIN,
    ROLE_PUBLIC_COMMENTER,
    ROLE_QA_REVIEWER,
)

# ---------------------------------------------------------------------------
# Opaque user identifiers
# ---------------------------------------------------------------------------

ADMIN_USER_ID = "admin-1"
ANALYST_USER_ID = "analyst-1"
QA_USER_ID = "qa-1"
MANAGER_USER_ID = "mgr-1"
LIAISON_USER_ID = "liaison-1"
INSPECTOR_1_USER_ID = "insp-1"
INSPECTOR_2_USER_ID = "insp-2"

UNKNOWN_ROLE_NAME = "AuditorGeneral"
UNKNOWN_ROLE_USER_ID = "audit-1"


def resident_user_id(n: int) -> str:
    """Stable opaque id for the nth public commenter / resident."""
    return f"resident-{n}"


# ---------------------------------------------------------------------------
# Ready-made header bundles
# ---------------------------------------------------------------------------

ADMIN_HEADERS: Dict[str, str] = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
ANALYST_HEADERS: Dict[str, str] = build_user_headers(ANALYST_USER_ID, ROLE_EJ_ANALYST)
QA_HEADERS: Dict[str, str] = build_user_headers(QA_USER_ID, ROLE_QA_REVIEWER)
MANAGER_HEADERS: Dict[str, str] = build_user_headers(MANAGER_USER_ID, ROLE_PERMIT_MANAGER)
LIAISON_HEADERS: Dict[str, str] = build_user_headers(LIAISON_USER_ID, ROLE_COMMUNITY_LIAISON)
INSPECTOR_1_HEADERS: Dict[str, str] = build_user_headers(INSPECTOR_1_USER_ID, ROLE_INSPECTOR)
INSPECTOR_2_HEADERS: Dict[str, str] = build_user_headers(INSPECTOR_2_USER_ID, ROLE_INSPECTOR)

# PRD §2.2: "If either header is absent or empty, the request is rejected".
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}

# PRD §2.2: a role string outside the declared eight.
UNKNOWN_ROLE_HEADERS: Dict[str, str] = build_user_headers(
    UNKNOWN_ROLE_USER_ID, UNKNOWN_ROLE_NAME
)


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": ADMIN_USER_ID, "role": ROLE_PROGRAM_ADMIN},
    "analyst": {"user_id": ANALYST_USER_ID, "role": ROLE_EJ_ANALYST},
    "qa": {"user_id": QA_USER_ID, "role": ROLE_QA_REVIEWER},
    "manager": {"user_id": MANAGER_USER_ID, "role": ROLE_PERMIT_MANAGER},
    "liaison": {"user_id": LIAISON_USER_ID, "role": ROLE_COMMUNITY_LIAISON},
    "inspector_1": {"user_id": INSPECTOR_1_USER_ID, "role": ROLE_INSPECTOR},
    "inspector_2": {"user_id": INSPECTOR_2_USER_ID, "role": ROLE_INSPECTOR},
}


def headers_for(alias: str) -> Dict[str, str]:
    """Header bundle for one of the opaque aliases in `TEST_USERS`."""
    user = TEST_USERS[alias]
    return build_user_headers(user["user_id"], user["role"])


# ---------------------------------------------------------------------------
# Identity builders
# ---------------------------------------------------------------------------


def make_applicant_headers(facility_id: str) -> Dict[str, str]:
    """Headers for the representative of `facility_id`.

    PRD §2.1: the `ApplicantRepresentative` role is backed by a Facility, so
    `X-User-ID` carries the facility's own `id`. Every ownership-gated call
    (`/submit`, `/resubmit`, `/withdraw`, application creation) must be made
    with the headers produced here for the *owning* facility.
    """
    return build_user_headers(facility_id, ROLE_APPLICANT_REPRESENTATIVE)


def make_commenter_headers(user_id: str) -> Dict[str, str]:
    """Headers for an opaque `PublicCommenter` such as `resident-6`."""
    return build_user_headers(user_id, ROLE_PUBLIC_COMMENTER)


def resident_headers(n: int) -> Dict[str, str]:
    """Headers for `resident-<n>` acting as a `PublicCommenter`."""
    return make_commenter_headers(resident_user_id(n))


def make_qa_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `QAReviewer` presenting an arbitrary `X-User-ID`.

    Used to exercise the segregation-of-duties guard, where the reviewer
    presents the author's own user id.
    """
    return build_user_headers(user_id, ROLE_QA_REVIEWER)


def make_inspector_headers(user_id: str) -> Dict[str, str]:
    """Headers for an `Inspector` presenting an arbitrary `X-User-ID`."""
    return build_user_headers(user_id, ROLE_INSPECTOR)


def make_analyst_headers(user_id: str) -> Dict[str, str]:
    """Headers for an `EJAnalyst` presenting an arbitrary `X-User-ID`."""
    return build_user_headers(user_id, ROLE_EJ_ANALYST)


def make_manager_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `PermitManager` presenting an arbitrary `X-User-ID`."""
    return build_user_headers(user_id, ROLE_PERMIT_MANAGER)


def make_liaison_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `CommunityLiaison` presenting an arbitrary `X-User-ID`."""
    return build_user_headers(user_id, ROLE_COMMUNITY_LIAISON)
