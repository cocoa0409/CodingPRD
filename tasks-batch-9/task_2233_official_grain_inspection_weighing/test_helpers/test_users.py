"""Pre-built identity headers for every role in the PRD.

Every request must carry a single identity header, `X-User-Id`, naming the
acting user, and for all five roles that value is an opaque operator
identifier: the canonical values are `admin_user`, `supervisor_user`,
`inspector_user`, `applicant_user` and `auditor_user`. The one place ownership
matters is applicant scope, so an applicant-id builder is supplied as well.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator identifiers.
ADMIN_USER_ID = "admin_user"
SUPERVISOR_USER_ID = "supervisor_user"
INSPECTOR_USER_ID = "inspector_user"
APPLICANT_USER_ID = "applicant_user"
AUDITOR_USER_ID = "auditor_user"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "ServiceAdmin"),
    "supervisor_headers": build_user_headers(SUPERVISOR_USER_ID, "SupervisingInspector"),
    "inspector_headers": build_user_headers(INSPECTOR_USER_ID, "LicensedInspector"),
    "applicant_headers": build_user_headers(APPLICANT_USER_ID, "ApplicantUser"),
    "auditor_headers": build_user_headers(AUDITOR_USER_ID, "Auditor"),
}

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
APPLICANT = TEST_USERS["applicant_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

# A request with no identity header at all.
NO_IDENTITY_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """Act as the `ApplicantUser` bound to one specific applicant account.

    When the header value is itself the `id` of an existing `Applicant` row,
    that row is the acting account — which is what applicant-scope checks
    compare against.
    """
    return build_user_headers(applicant_id, "ApplicantUser")


def make_identity_headers(user_id: str) -> Dict[str, str]:
    """Send only `X-User-Id`, so the role must be resolved from that value
    alone. Used to exercise an unknown identity."""
    return {"X-User-Id": user_id, "Content-Type": "application/json"}
