"""Actor identities and header builders.

Per §2.1 every request carries `X-User-ID` and `X-User-Role`. Three roles are
entity-backed — `Applicant` sends the acting `Household` id, `Contractor` the
acting `Contractor` id, `FieldInspector` the acting `Inspector` id — so headers
for those roles must be built per entity. `ProgramReviewer` and `ProgramAdmin`
carry opaque staff identifiers.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque staff identifiers (§2.1). Two of each so segregation-of-duties
# scenarios (§2.9) can use a different actor for the second decision.
ADMIN_ONE = "admin-1"
ADMIN_TWO = "admin-2"
REVIEWER_ONE = "reviewer-1"
REVIEWER_TWO = "reviewer-2"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": build_user_headers(ADMIN_ONE, UserRole.PROGRAM_ADMIN),
    "admin_two": build_user_headers(ADMIN_TWO, UserRole.PROGRAM_ADMIN),
    "reviewer": build_user_headers(REVIEWER_ONE, UserRole.PROGRAM_REVIEWER),
    "reviewer_two": build_user_headers(REVIEWER_TWO, UserRole.PROGRAM_REVIEWER),
}

ADMIN_HEADERS = TEST_USERS["admin"]
ADMIN_TWO_HEADERS = TEST_USERS["admin_two"]
REVIEWER_HEADERS = TEST_USERS["reviewer"]
REVIEWER_TWO_HEADERS = TEST_USERS["reviewer_two"]


def make_applicant_headers(household_id: str) -> Dict[str, str]:
    """Headers for the `Applicant` who owns `household_id`."""
    return build_user_headers(household_id, UserRole.APPLICANT)


def make_contractor_headers(contractor_id: str) -> Dict[str, str]:
    """Headers for the `Contractor` identified by `contractor_id`."""
    return build_user_headers(contractor_id, UserRole.CONTRACTOR)


def make_field_inspector_headers(inspector_id: str) -> Dict[str, str]:
    """Headers for the `FieldInspector` identified by `inspector_id`."""
    return build_user_headers(inspector_id, UserRole.FIELD_INSPECTOR)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `ProgramAdmin` acting under an arbitrary opaque id."""
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN)


def make_reviewer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a `ProgramReviewer` acting under an arbitrary opaque id."""
    return build_user_headers(user_id, UserRole.PROGRAM_REVIEWER)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but no `X-User-ID`, for the rung-1 check."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying an identity but no `X-User-Role`, for the rung-2 check."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


__all__ = [
    "ADMIN_ONE",
    "ADMIN_TWO",
    "REVIEWER_ONE",
    "REVIEWER_TWO",
    "TEST_USERS",
    "ADMIN_HEADERS",
    "ADMIN_TWO_HEADERS",
    "REVIEWER_HEADERS",
    "REVIEWER_TWO_HEADERS",
    "make_applicant_headers",
    "make_contractor_headers",
    "make_field_inspector_headers",
    "make_admin_headers",
    "make_reviewer_headers",
    "headers_without_user_id",
    "headers_without_role",
]
