"""Caller identities.

Six of the seven roles are opaque operator identities, so a fixed user id per
role is enough. The `Originator` role is entity-backed: its `X-User-ID` must be
the id of the acting originator row, so those headers are always built per test
with :func:`make_originator_headers`.
"""
from prd_bench_local_runner.testing import build_user_headers

from test_helpers.types import UserRole

# Opaque operator identifiers (PRD 2.1).
ANALYST_USER_ID = "user-licensing-analyst-01"
SECOND_ANALYST_USER_ID = "user-licensing-analyst-02"
DESIGNER_USER_ID = "user-compensation-designer-01"
SECOND_DESIGNER_USER_ID = "user-compensation-designer-02"
OFFICER_USER_ID = "user-compliance-officer-01"
SECOND_OFFICER_USER_ID = "user-compliance-officer-02"
THIRD_OFFICER_USER_ID = "user-compliance-officer-03"
LOAN_OPS_USER_ID = "user-loan-operations-01"
EXAMINER_USER_ID = "user-examination-coordinator-01"
ADMIN_USER_ID = "user-platform-admin-01"

# Placeholder identity for the entity-backed role; only used where the test
# deliberately wants a non-owning originator.
UNOWNED_ORIGINATOR_USER_ID = "00000000-0000-4000-8000-0000000000ff"


TEST_USERS = {
    UserRole.LICENSING_ANALYST.value: build_user_headers(
        ANALYST_USER_ID, UserRole.LICENSING_ANALYST.value
    ),
    UserRole.COMPENSATION_DESIGNER.value: build_user_headers(
        DESIGNER_USER_ID, UserRole.COMPENSATION_DESIGNER.value
    ),
    UserRole.COMPLIANCE_OFFICER.value: build_user_headers(
        OFFICER_USER_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
    UserRole.ORIGINATOR.value: build_user_headers(
        UNOWNED_ORIGINATOR_USER_ID, UserRole.ORIGINATOR.value
    ),
    UserRole.LOAN_OPERATIONS.value: build_user_headers(
        LOAN_OPS_USER_ID, UserRole.LOAN_OPERATIONS.value
    ),
    UserRole.EXAMINATION_COORDINATOR.value: build_user_headers(
        EXAMINER_USER_ID, UserRole.EXAMINATION_COORDINATOR.value
    ),
    UserRole.PLATFORM_ADMIN.value: build_user_headers(
        ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value
    ),
}


def analyst_headers(user_id=ANALYST_USER_ID):
    """Headers for the licensing desk."""
    return build_user_headers(user_id, UserRole.LICENSING_ANALYST.value)


def designer_headers(user_id=DESIGNER_USER_ID):
    """Headers for a compensation plan designer."""
    return build_user_headers(user_id, UserRole.COMPENSATION_DESIGNER.value)


def officer_headers(user_id=OFFICER_USER_ID):
    """Headers for a compliance officer."""
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def loan_ops_headers(user_id=LOAN_OPS_USER_ID):
    """Headers for the closing and servicing desk."""
    return build_user_headers(user_id, UserRole.LOAN_OPERATIONS.value)


def examiner_headers(user_id=EXAMINER_USER_ID):
    """Headers for the examination coordinator."""
    return build_user_headers(user_id, UserRole.EXAMINATION_COORDINATOR.value)


def admin_headers(user_id=ADMIN_USER_ID):
    """Headers for the platform administrator, who owns clock and sweep."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_originator_headers(originator_id):
    """Headers for the entity-backed originator role.

    `X-User-ID` must carry the acting originator's own row id, because every
    ownership check compares the target's `originator_id` to it (PRD 2.1).
    """
    return build_user_headers(originator_id, UserRole.ORIGINATOR.value)
