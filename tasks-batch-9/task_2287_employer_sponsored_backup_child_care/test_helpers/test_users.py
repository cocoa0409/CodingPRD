"""Role headers.

Five peer roles authenticate with X-User-ID plus X-User-Role.  Two of them are
entity-backed: a provider_manager is recognised through the Provider it owns
(owner_user_id) and an employee_user through the Employee row that carries the
same user_id.  For any ownership-gated call those two roles MUST be built with
the matching builder below so the header identity resolves to the intended row.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Shared identities.  Safe for calls that are not ownership-gated.
# --------------------------------------------------------------------------
NETWORK_ADMIN_USER_ID = "u_na_1"
BENEFITS_ADMIN_USER_ID = "u_ba_1"
CARE_COORDINATOR_USER_ID = "u_cc_1"
PROVIDER_MANAGER_USER_ID = "u_pm_1"
EMPLOYEE_USER_USER_ID = "u_ee_1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "network_admin": build_user_headers(NETWORK_ADMIN_USER_ID, UserRole.NETWORK_ADMIN.value),
    "benefits_admin": build_user_headers(BENEFITS_ADMIN_USER_ID, UserRole.BENEFITS_ADMIN.value),
    "care_coordinator": build_user_headers(
        CARE_COORDINATOR_USER_ID, UserRole.CARE_COORDINATOR.value
    ),
    "provider_manager": build_user_headers(
        PROVIDER_MANAGER_USER_ID, UserRole.PROVIDER_MANAGER.value
    ),
    "employee_user": build_user_headers(EMPLOYEE_USER_USER_ID, UserRole.EMPLOYEE_USER.value),
}


# --------------------------------------------------------------------------
# Builders for roles whose authority is scoped to a specific entity
# --------------------------------------------------------------------------
def make_network_admin_headers(user_id: str = NETWORK_ADMIN_USER_ID) -> Dict[str, str]:
    """network_admin is not entity-backed; the id only distinguishes actors."""
    return build_user_headers(user_id, UserRole.NETWORK_ADMIN.value)


def make_benefits_admin_headers(user_id: str = BENEFITS_ADMIN_USER_ID) -> Dict[str, str]:
    """benefits_admin is not entity-backed; the id only distinguishes actors."""
    return build_user_headers(user_id, UserRole.BENEFITS_ADMIN.value)


def make_care_coordinator_headers(user_id: str = CARE_COORDINATOR_USER_ID) -> Dict[str, str]:
    """care_coordinator is not entity-backed; the id only distinguishes actors."""
    return build_user_headers(user_id, UserRole.CARE_COORDINATOR.value)


def make_provider_manager_headers(owner_user_id: str) -> Dict[str, str]:
    """Headers for the manager of the provider whose owner_user_id is given."""
    return build_user_headers(owner_user_id, UserRole.PROVIDER_MANAGER.value)


def make_employee_user_headers(user_id: str) -> Dict[str, str]:
    """Headers for the employee whose Employee.user_id is given."""
    return build_user_headers(user_id, UserRole.EMPLOYEE_USER.value)


def unauthenticated_headers() -> Dict[str, str]:
    """Headers with no X-User-ID at all."""
    return {"Content-Type": "application/json"}
