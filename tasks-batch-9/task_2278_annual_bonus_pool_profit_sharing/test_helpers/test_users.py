"""Role headers.

Four of the six roles act with an opaque operator identifier, so their headers
can be pre-built. Two roles are entity-backed and must be threaded with a real
identifier at call time: a ``BusinessUnitManager`` acts as the ``BusinessUnit``
id and an ``Employee`` acts as the ``Participant`` id. Use the ``make_*``
builders for those, never a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Distinct committee operators, so that segregation-of-duties rules can be
# exercised (and avoided) deliberately.
CC_SCORECARD = "cc_scorecard"
CC_CERTIFIER = "cc_certifier"
CC_LOCKER = "cc_locker"
CC_ADJUDICATOR = "cc_adjudicator"
CC_REVERSER = "cc_reverser"

PLAN_ADMIN_USER = "pa_1"
PLAN_ADMIN_USER_ALT = "pa_2"
HRBP_USER = "hrbp_1"
HRBP_USER_ALT = "hrbp_2"
FINANCE_USER = "fc_1"

TEST_USERS = {
    "plan_admin_headers": build_user_headers(PLAN_ADMIN_USER, UserRole.PLAN_ADMIN.value),
    "plan_admin_alt_headers": build_user_headers(
        PLAN_ADMIN_USER_ALT, UserRole.PLAN_ADMIN.value
    ),
    "committee_headers": build_user_headers(
        CC_CERTIFIER, UserRole.COMPENSATION_COMMITTEE.value
    ),
    "committee_scorecard_headers": build_user_headers(
        CC_SCORECARD, UserRole.COMPENSATION_COMMITTEE.value
    ),
    "committee_locker_headers": build_user_headers(
        CC_LOCKER, UserRole.COMPENSATION_COMMITTEE.value
    ),
    "committee_adjudicator_headers": build_user_headers(
        CC_ADJUDICATOR, UserRole.COMPENSATION_COMMITTEE.value
    ),
    "committee_reverser_headers": build_user_headers(
        CC_REVERSER, UserRole.COMPENSATION_COMMITTEE.value
    ),
    "hr_headers": build_user_headers(HRBP_USER, UserRole.HR_BUSINESS_PARTNER.value),
    "hr_alt_headers": build_user_headers(
        HRBP_USER_ALT, UserRole.HR_BUSINESS_PARTNER.value
    ),
    "finance_headers": build_user_headers(
        FINANCE_USER, UserRole.FINANCE_CONTROLLER.value
    ),
}


def make_manager_headers(business_unit_id: str) -> dict:
    """Headers for the manager of a specific business unit."""
    return build_user_headers(business_unit_id, UserRole.BUSINESS_UNIT_MANAGER.value)


def make_employee_headers(participant_id: str) -> dict:
    """Headers for a specific plan participant."""
    return build_user_headers(participant_id, UserRole.EMPLOYEE.value)


def make_committee_headers(user_id: str) -> dict:
    """Headers for a named committee operator."""
    return build_user_headers(user_id, UserRole.COMPENSATION_COMMITTEE.value)


def make_plan_admin_headers(user_id: str) -> dict:
    """Headers for a named plan-admin operator."""
    return build_user_headers(user_id, UserRole.PLAN_ADMIN.value)


def make_hr_headers(user_id: str) -> dict:
    """Headers for a named HR business partner operator."""
    return build_user_headers(user_id, UserRole.HR_BUSINESS_PARTNER.value)


def make_finance_headers(user_id: str) -> dict:
    """Headers for a named finance controller operator."""
    return build_user_headers(user_id, UserRole.FINANCE_CONTROLLER.value)


# Every role name recognized by the API, for role-matrix parameterization.
ALL_ROLE_NAMES = [role.value for role in UserRole]
