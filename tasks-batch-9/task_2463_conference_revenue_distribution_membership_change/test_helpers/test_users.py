"""Canonical test identities and header builders.

Seven of the eight roles are opaque staff identities: any user id carrying the
role is equivalent.  MemberRepresentative is different - it is entity-backed, so
its ``X-User-ID`` must be the id of the member institution it speaks for, which
is why representative headers can only be built once a member exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Stable ids for the opaque staff roles.  Distinct ids per role matter for the
# segregation-of-duties rules, which compare the acting user against the user
# recorded on the run being posted or attested.
COMMISSIONER_USER_ID = "u_com_1"
FINANCE_OFFICER_USER_ID = "u_fin_1"
TREASURER_USER_ID = "u_trs_1"
AUDITOR_USER_ID = "u_aud_1"
COMPLIANCE_OFFICER_USER_ID = "u_cmp_1"
SCHEDULE_COORDINATOR_USER_ID = "u_sch_1"
PLATFORM_ADMIN_USER_ID = "u_adm_1"

# Second identities in the same role, used where a rule requires two distinct
# users holding the same role.
FINANCE_OFFICER_USER_ID_2 = "u_fin_2"
TREASURER_USER_ID_2 = "u_trs_2"
AUDITOR_USER_ID_2 = "u_aud_2"
COMMISSIONER_USER_ID_2 = "u_com_2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "commissioner": {
        "user_id": COMMISSIONER_USER_ID,
        "role": UserRole.COMMISSIONER.value,
    },
    "finance_officer": {
        "user_id": FINANCE_OFFICER_USER_ID,
        "role": UserRole.FINANCE_OFFICER.value,
    },
    "treasurer": {
        "user_id": TREASURER_USER_ID,
        "role": UserRole.TREASURER.value,
    },
    "auditor": {
        "user_id": AUDITOR_USER_ID,
        "role": UserRole.AUDITOR.value,
    },
    "compliance_officer": {
        "user_id": COMPLIANCE_OFFICER_USER_ID,
        "role": UserRole.COMPLIANCE_OFFICER.value,
    },
    "schedule_coordinator": {
        "user_id": SCHEDULE_COORDINATOR_USER_ID,
        "role": UserRole.SCHEDULE_COORDINATOR.value,
    },
    "platform_admin": {
        "user_id": PLATFORM_ADMIN_USER_ID,
        "role": UserRole.PLATFORM_ADMIN.value,
    },
}


def headers_for(user_key: str) -> Dict[str, str]:
    """Headers for one of the canonical staff identities."""
    user = TEST_USERS[user_key]
    return build_user_headers(user["user_id"], user["role"])


def make_commissioner_headers(user_id: str = COMMISSIONER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.COMMISSIONER.value)


def make_finance_officer_headers(
    user_id: str = FINANCE_OFFICER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.FINANCE_OFFICER.value)


def make_treasurer_headers(user_id: str = TREASURER_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.TREASURER.value)


def make_auditor_headers(user_id: str = AUDITOR_USER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.AUDITOR.value)


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_schedule_coordinator_headers(
    user_id: str = SCHEDULE_COORDINATOR_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.SCHEDULE_COORDINATOR.value)


def make_platform_admin_headers(
    user_id: str = PLATFORM_ADMIN_USER_ID,
) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_member_representative_headers(member_id: str) -> Dict[str, str]:
    """Headers for the representative of ``member_id``.

    A MemberRepresentative user id is the id of the member institution it
    represents, so ownership checks compare this header against the member the
    request touches.
    """
    return build_user_headers(member_id, UserRole.MEMBER_REPRESENTATIVE.value)
