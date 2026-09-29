"""
Test identities and auth header builders.

The PRD splits identity handling by role:

- Investor: `X-User-ID` MUST be the Investor's own `id`, so an Investor header
  can only be built AFTER the investor row exists. Use `make_investor_headers`
  with the created investor's id — never a fixed constant.
- FundManager: `X-User-ID` is an opaque operator handle compared against
  `Fund.manager_user_id`. It must match the handle the fund was created with.
- ComplianceOfficer / PlatformAdmin: opaque operator handles recorded on the
  rows they touch (`measured_by_user_id`, `certified_by_user_id`,
  `decided_by_user_id`, `requested_by_user_id`).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FUND_MANAGER,
    ROLE_INVESTOR,
    ROLE_PLATFORM_ADMIN,
)

# --- opaque operator handles ---------------------------------------------
ADMIN_USER_ID = "admin-1"
FUND_MANAGER_USER_ID = "mgr-fund-1"
OTHER_FUND_MANAGER_USER_ID = "mgr-fund-2"
OFFICER_MEASURER_USER_ID = "co-measurer-1"
OFFICER_CERTIFIER_USER_ID = "co-certifier-1"

# Placeholder used only where the Investor id is not yet known; a real
# Investor call MUST thread the created investor's id instead.
PLACEHOLDER_INVESTOR_ID = "00000000-0000-4000-8000-000000000001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    "platform_admin": {
        "user_id": ADMIN_USER_ID,
        "role": ROLE_PLATFORM_ADMIN,
    },
    "fund_manager": {
        "user_id": FUND_MANAGER_USER_ID,
        "role": ROLE_FUND_MANAGER,
    },
    "other_fund_manager": {
        "user_id": OTHER_FUND_MANAGER_USER_ID,
        "role": ROLE_FUND_MANAGER,
    },
    "compliance_officer_measurer": {
        "user_id": OFFICER_MEASURER_USER_ID,
        "role": ROLE_COMPLIANCE_OFFICER,
    },
    "compliance_officer_certifier": {
        "user_id": OFFICER_CERTIFIER_USER_ID,
        "role": ROLE_COMPLIANCE_OFFICER,
    },
    "investor": {
        "user_id": PLACEHOLDER_INVESTOR_ID,
        "role": ROLE_INVESTOR,
    },
}


# --- per-instance header builders ----------------------------------------


def make_investor_headers(user_id: str) -> Dict[str, str]:
    """Investor headers for a specific Investor id (identity == entity id)."""
    return build_user_headers(user_id, ROLE_INVESTOR)


def make_fund_manager_headers(user_id: str = FUND_MANAGER_USER_ID) -> Dict[str, str]:
    """FundManager headers for a specific opaque manager handle."""
    return build_user_headers(user_id, ROLE_FUND_MANAGER)


def make_compliance_officer_headers(
    user_id: str = OFFICER_CERTIFIER_USER_ID,
) -> Dict[str, str]:
    """ComplianceOfficer headers for a specific opaque officer handle."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> Dict[str, str]:
    """PlatformAdmin headers for a specific opaque admin handle."""
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user_id/role pair, for role-rejection probes."""
    return build_user_headers(user_id, role)


# --- ready-made headers for the opaque roles -----------------------------
# Investor headers are intentionally absent: they must be built per investor.
ADMIN_HEADERS = make_platform_admin_headers(ADMIN_USER_ID)
MANAGER_HEADERS = make_fund_manager_headers(FUND_MANAGER_USER_ID)
OTHER_MANAGER_HEADERS = make_fund_manager_headers(OTHER_FUND_MANAGER_USER_ID)
MEASURER_HEADERS = make_compliance_officer_headers(OFFICER_MEASURER_USER_ID)
CERTIFIER_HEADERS = make_compliance_officer_headers(OFFICER_CERTIFIER_USER_ID)
