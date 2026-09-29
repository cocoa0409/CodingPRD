"""Identity threading for the six roles.

Two of the roles carry an opaque operator identifier that the server never
compares to a persisted row, so a fixed constant is correct for them. The other
four are entity backed: the presented X-User-ID must resolve to a real
StaffMember or Requester row, and ownership plus segregation-of-duties checks
compare it field by field. Those four therefore have per-instance builders and
must never be called through a shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CLERK,
    ROLE_COUNSEL,
    ROLE_REQUESTER,
    ROLE_REVIEWER,
    ROLE_SUPERVISOR,
    ROLE_TECHNICIAN,
)

# ------------------------------------------------------------ opaque roles
CLERK_USER_ID = "clerk-1"
SUPERVISOR_USER_ID = "supv-1"

CLERK_HEADERS: Dict[str, str] = build_user_headers(CLERK_USER_ID, ROLE_CLERK)
SUPERVISOR_HEADERS: Dict[str, str] = build_user_headers(SUPERVISOR_USER_ID, ROLE_SUPERVISOR)

# Only the two opaque roles may be addressed through a shared constant.
TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_CLERK: CLERK_HEADERS,
    ROLE_SUPERVISOR: SUPERVISOR_HEADERS,
}


def make_clerk_headers(user_id: str = CLERK_USER_ID) -> Dict[str, str]:
    """Headers for the intake and production desk (opaque identifier)."""
    return build_user_headers(user_id, ROLE_CLERK)


def make_supervisor_headers(user_id: str = SUPERVISOR_USER_ID) -> Dict[str, str]:
    """Headers for the unit supervisor (opaque identifier)."""
    return build_user_headers(user_id, ROLE_SUPERVISOR)


# ------------------------------------------------------ entity-backed roles
def make_counsel_headers(staff_id: str) -> Dict[str, str]:
    """Headers for an attorney; staff_id must be a persisted StaffMember id."""
    return build_user_headers(staff_id, ROLE_COUNSEL)


def make_technician_headers(staff_id: str) -> Dict[str, str]:
    """Headers for a redaction operator; compared to assigned_technician_id."""
    return build_user_headers(staff_id, ROLE_TECHNICIAN)


def make_reviewer_headers(staff_id: str) -> Dict[str, str]:
    """Headers for a quality reviewer; compared to qa_reviewer_id."""
    return build_user_headers(staff_id, ROLE_REVIEWER)


def make_requester_headers(requester_id: str) -> Dict[str, str]:
    """Headers for a filer; compared to a request's requester_id."""
    return build_user_headers(requester_id, ROLE_REQUESTER)


def headers_for_role(role: str, user_id: str) -> Dict[str, str]:
    """Generic builder used by role-matrix tests that iterate over role names."""
    return build_user_headers(user_id, role)
