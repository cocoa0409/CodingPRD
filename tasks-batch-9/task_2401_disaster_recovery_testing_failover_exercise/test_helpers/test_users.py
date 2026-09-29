"""Acting identities and the header builders for the six declared roles.

Five of the six roles are stakeholder-backed: `X-User-ID` must be the `id` of a
persisted `Stakeholder` row whose `status` is `ACTIVE` and whose `org_roles`
array carries the matching organisational hat.  Header builders for those five
therefore take the stakeholder id created by the test.  `PlatformAdmin` alone
carries an opaque operator identifier that resolves against nothing.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

PLATFORM_ADMIN_USER_ID = "platform-admin-operator"

TEST_USERS = {
    "platform_admin": {
        "user_id": PLATFORM_ADMIN_USER_ID,
        "role": UserRole.PLATFORM_ADMIN.value,
    },
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_USER_ID) -> dict:
    """Headers for the opaque administrator identity."""
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_resilience_coordinator_headers(stakeholder_id: str) -> dict:
    return build_user_headers(stakeholder_id, UserRole.RESILIENCE_COORDINATOR.value)


def make_business_owner_headers(stakeholder_id: str) -> dict:
    return build_user_headers(stakeholder_id, UserRole.BUSINESS_OWNER.value)


def make_it_operator_headers(stakeholder_id: str) -> dict:
    return build_user_headers(stakeholder_id, UserRole.IT_OPERATOR.value)


def make_risk_approver_headers(stakeholder_id: str) -> dict:
    return build_user_headers(stakeholder_id, UserRole.RISK_APPROVER.value)


def make_audit_liaison_headers(stakeholder_id: str) -> dict:
    return build_user_headers(stakeholder_id, UserRole.AUDIT_LIAISON.value)


PLATFORM_ADMIN_HEADERS = make_platform_admin_headers()
