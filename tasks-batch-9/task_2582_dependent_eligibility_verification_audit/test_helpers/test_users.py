"""Acting principals.

Four of the five roles supply an opaque operator identifier that the server
never resolves against a stored row, so a module-level constant is safe for
them. An ``Employee`` is different: its ``X-User-ID`` is the ``id`` of the
acting employee record, so its headers must be built per employee with
:func:`employee_headers`.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    APPEAL_REVIEWER as APPEAL_REVIEWER_ROLE,
    EMPLOYEE as EMPLOYEE_ROLE,
    PROGRAM_ADMIN as PROGRAM_ADMIN_ROLE,
    RECOVERY_AGENT as RECOVERY_AGENT_ROLE,
    VERIFICATION_ANALYST as VERIFICATION_ANALYST_ROLE,
)
from .types import Headers

# --------------------------------------------------- opaque operator identifiers
PROGRAM_ADMIN_USER_ID = "u_admin_1"
PROGRAM_ADMIN_ALT_USER_ID = "u_admin_2"
ANALYST_USER_ID = "u_analyst_1"
ANALYST_ALT_USER_ID = "u_analyst_2"
REVIEWER_USER_ID = "u_appeal_1"
REVIEWER_ALT_USER_ID = "u_appeal_2"
RECOVERY_USER_ID = "u_recovery_1"
RECOVERY_ALT_USER_ID = "u_recovery_2"

PROGRAM_ADMIN: Headers = build_user_headers(PROGRAM_ADMIN_USER_ID, PROGRAM_ADMIN_ROLE)
PROGRAM_ADMIN_ALT: Headers = build_user_headers(
    PROGRAM_ADMIN_ALT_USER_ID, PROGRAM_ADMIN_ROLE
)

ANALYST: Headers = build_user_headers(ANALYST_USER_ID, VERIFICATION_ANALYST_ROLE)
ANALYST_ALT: Headers = build_user_headers(ANALYST_ALT_USER_ID, VERIFICATION_ANALYST_ROLE)

REVIEWER: Headers = build_user_headers(REVIEWER_USER_ID, APPEAL_REVIEWER_ROLE)
REVIEWER_ALT: Headers = build_user_headers(REVIEWER_ALT_USER_ID, APPEAL_REVIEWER_ROLE)

RECOVERY_AGENT: Headers = build_user_headers(RECOVERY_USER_ID, RECOVERY_AGENT_ROLE)
RECOVERY_AGENT_ALT: Headers = build_user_headers(
    RECOVERY_ALT_USER_ID, RECOVERY_AGENT_ROLE
)

# The same operator identifier acting under two roles: what the
# segregation-of-duties comparison is written against.
DUAL_HAT_USER_ID = "u_dual_1"
DUAL_HAT_ANALYST: Headers = build_user_headers(
    DUAL_HAT_USER_ID, VERIFICATION_ANALYST_ROLE
)
DUAL_HAT_REVIEWER: Headers = build_user_headers(DUAL_HAT_USER_ID, APPEAL_REVIEWER_ROLE)


def employee_headers(employee_id: str) -> Headers:
    """Headers for the ``Employee`` whose record id is ``employee_id``."""
    return build_user_headers(employee_id, EMPLOYEE_ROLE)


def role_headers(role: str, user_id: str = "u_operator_1") -> Headers:
    """Headers for an arbitrary role name, including undeclared ones."""
    return build_user_headers(user_id, role)


def analyst_headers(user_id: str) -> Headers:
    """A ``VerificationAnalyst`` acting under a specific operator identifier."""
    return build_user_headers(user_id, VERIFICATION_ANALYST_ROLE)


def reviewer_headers(user_id: str) -> Headers:
    """An ``AppealReviewer`` acting under a specific operator identifier."""
    return build_user_headers(user_id, APPEAL_REVIEWER_ROLE)


def headers_for_each_role(employee_id: str) -> Dict[str, Headers]:
    """Every declared role, with the employee-backed identity threaded correctly."""
    return {
        PROGRAM_ADMIN_ROLE: PROGRAM_ADMIN,
        VERIFICATION_ANALYST_ROLE: ANALYST,
        APPEAL_REVIEWER_ROLE: REVIEWER,
        RECOVERY_AGENT_ROLE: RECOVERY_AGENT,
        EMPLOYEE_ROLE: employee_headers(employee_id),
    }


MISSING_ROLE_HEADERS: Headers = {"X-User-ID": PROGRAM_ADMIN_USER_ID}
MISSING_USER_HEADERS: Headers = {"X-User-Role": PROGRAM_ADMIN_ROLE}
NO_HEADERS: Headers = {}
UNKNOWN_ROLE_HEADERS: Headers = build_user_headers(
    PROGRAM_ADMIN_USER_ID, "BenefitsDirector"
)
