"""Acting identities.

The PRD declares six roles. Five of them are opaque user identifiers; a
``TreasuryOfficer`` is different — its ``X-User-ID`` is the ``id`` of the acting
``MemberBank``, so treasury headers must always be built from a real member id
through :func:`make_treasury_officer_headers`.

Distinct opaque identifiers are deliberately reserved for the two segregation of
duties rules: approval versus funding, and raising versus waiving a finding.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque acting identifiers.
SYSTEM_ADMIN_USER_ID = "system-admin-1"
CREDIT_OFFICER_ONE_USER_ID = "credit-officer-1"
CREDIT_OFFICER_TWO_USER_ID = "credit-officer-2"
CUSTODIAN_USER_ID = "custodian-1"
AUDITOR_USER_ID = "auditor-1"
COMMUNITY_MANAGER_USER_ID = "community-manager-1"

# A treasury identifier that belongs to no member: useful for probes that must
# fail before any ownership check can run.
UNSCOPED_TREASURY_USER_ID = "treasury-officer-unscoped"

# One human wearing two hats, used by the segregation of duties translations.
SHARED_HUMAN_USER_ID = "user-77"


def make_headers(user_id: str, role: UserRole) -> dict:
    """Headers for an arbitrary user identifier and role."""
    return build_user_headers(user_id, role.value)


def system_admin_headers(user_id: str = SYSTEM_ADMIN_USER_ID) -> dict:
    return make_headers(user_id, UserRole.SYSTEM_ADMIN)


def credit_officer_headers(user_id: str = CREDIT_OFFICER_ONE_USER_ID) -> dict:
    return make_headers(user_id, UserRole.CREDIT_OFFICER)


def custodian_headers(user_id: str = CUSTODIAN_USER_ID) -> dict:
    return make_headers(user_id, UserRole.COLLATERAL_CUSTODIAN)


def auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    return make_headers(user_id, UserRole.COLLATERAL_REVIEW_AUDITOR)


def community_manager_headers(user_id: str = COMMUNITY_MANAGER_USER_ID) -> dict:
    return make_headers(user_id, UserRole.COMMUNITY_LENDING_MANAGER)


def make_treasury_officer_headers(member_bank_id: str) -> dict:
    """Treasury headers whose ``X-User-ID`` is the acting member bank's ``id``."""
    return make_headers(member_bank_id, UserRole.TREASURY_OFFICER)


TEST_USERS = {
    "system_admin": system_admin_headers(),
    "credit_officer": credit_officer_headers(CREDIT_OFFICER_ONE_USER_ID),
    "credit_officer_two": credit_officer_headers(CREDIT_OFFICER_TWO_USER_ID),
    "collateral_custodian": custodian_headers(),
    "collateral_review_auditor": auditor_headers(),
    "community_lending_manager": community_manager_headers(),
    "unscoped_treasury_officer": make_treasury_officer_headers(
        UNSCOPED_TREASURY_USER_ID
    ),
}
