"""Pre-built role headers for every role in the PRD.

Every role in this API carries an opaque identity: `X-User-ID` is an operator
identifier that is never compared against any entity's `id`. Shared constants
are therefore the canonical form for each role. The per-operator builders
exist for the two inequality comparisons the server does perform between two
operators (family certification and lot deviation acceptance) and for the
visibility filter applied to a `ChannelPartner` listing a part's requests.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# ---------------------------------------------------------------------------
# Canonical operators
# ---------------------------------------------------------------------------

PLANT_ADMIN_USER_ID = "pa-owen"
CERTIFICATION_ENGINEER_USER_ID = "ce-hana"
COMPLIANCE_OFFICER_USER_ID = "co-ravi"
QUALITY_ENGINEER_USER_ID = "qe-mika"
PRODUCTION_PLANNER_USER_ID = "pp-luis"
CHANNEL_PARTNER_USER_ID = "cp-dealer-77"

# Second operators, used where a workflow requires two distinct people.
SECOND_CERTIFICATION_ENGINEER_USER_ID = "ce-tomas"
SECOND_COMPLIANCE_OFFICER_USER_ID = "co-elena"
SECOND_QUALITY_ENGINEER_USER_ID = "qe-priya"
SECOND_CHANNEL_PARTNER_USER_ID = "cp-dealer-99"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "plant_admin_headers": build_user_headers(
        PLANT_ADMIN_USER_ID, UserRole.PLANT_ADMIN.value
    ),
    "certification_engineer_headers": build_user_headers(
        CERTIFICATION_ENGINEER_USER_ID, UserRole.CERTIFICATION_ENGINEER.value
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
    "quality_engineer_headers": build_user_headers(
        QUALITY_ENGINEER_USER_ID, UserRole.QUALITY_ENGINEER.value
    ),
    "production_planner_headers": build_user_headers(
        PRODUCTION_PLANNER_USER_ID, UserRole.PRODUCTION_PLANNER.value
    ),
    "channel_partner_headers": build_user_headers(
        CHANNEL_PARTNER_USER_ID, UserRole.CHANNEL_PARTNER.value
    ),
    # Second operators for the two segregation-of-duties comparisons.
    "second_certification_engineer_headers": build_user_headers(
        SECOND_CERTIFICATION_ENGINEER_USER_ID, UserRole.CERTIFICATION_ENGINEER.value
    ),
    "second_compliance_officer_headers": build_user_headers(
        SECOND_COMPLIANCE_OFFICER_USER_ID, UserRole.COMPLIANCE_OFFICER.value
    ),
    "second_quality_engineer_headers": build_user_headers(
        SECOND_QUALITY_ENGINEER_USER_ID, UserRole.QUALITY_ENGINEER.value
    ),
    "second_channel_partner_headers": build_user_headers(
        SECOND_CHANNEL_PARTNER_USER_ID, UserRole.CHANNEL_PARTNER.value
    ),
}

ALL_ROLE_NAMES = [role.value for role in UserRole]

PLANT_READ_ROLE_NAMES = [
    UserRole.PLANT_ADMIN.value,
    UserRole.CERTIFICATION_ENGINEER.value,
    UserRole.COMPLIANCE_OFFICER.value,
    UserRole.QUALITY_ENGINEER.value,
    UserRole.PRODUCTION_PLANNER.value,
]


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary operator acting under an arbitrary role."""
    return build_user_headers(user_id, role)


def make_plant_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PLANT_ADMIN.value)


def make_certification_engineer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CERTIFICATION_ENGINEER.value)


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.COMPLIANCE_OFFICER.value)


def make_quality_engineer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.QUALITY_ENGINEER.value)


def make_production_planner_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.PRODUCTION_PLANNER.value)


def make_channel_partner_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, UserRole.CHANNEL_PARTNER.value)


def headers_for_role(role: str, user_id: str = "operator-generic") -> Dict[str, str]:
    """Headers for the named role, using a generic operator identifier."""
    return build_user_headers(user_id, role)
