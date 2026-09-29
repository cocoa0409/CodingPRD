"""Role headers.

Five of the seven roles carry an opaque user identifier; two are entity backed
and their X-User-ID must be the id of the Operator or Manufacturer the caller
acts for. Shared constants cover the opaque roles; the make_*_headers builders
cover per-instance identity, which is mandatory for the entity-backed roles and
for any check that compares two opaque users to each other.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --------------------------------------------------------------------------
# Opaque user identifiers
# --------------------------------------------------------------------------

ADMIN_USER_ID = "admin-1"
NAM_USER_ID = "nam-1"
NAM_ALT_USER_ID = "nam-2"
ANALYST_USER_ID = "analyst-1"
ANALYST_ALT_USER_ID = "analyst-2"
ACCOUNTANT_USER_ID = "acct-1"
ACCOUNTANT_ALT_USER_ID = "acct-2"
AUDITOR_USER_ID = "auditor-1"
AUDITOR_ALT_USER_ID = "auditor-2"


# --------------------------------------------------------------------------
# Per-instance header builders
# --------------------------------------------------------------------------

def make_system_admin_headers(user_id: str = ADMIN_USER_ID):
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)


def make_national_account_manager_headers(user_id: str = NAM_USER_ID):
    return build_user_headers(user_id, UserRole.NATIONAL_ACCOUNT_MANAGER.value)


def make_pricing_analyst_headers(user_id: str = ANALYST_USER_ID):
    return build_user_headers(user_id, UserRole.PRICING_ANALYST.value)


def make_rebate_accountant_headers(user_id: str = ACCOUNTANT_USER_ID):
    return build_user_headers(user_id, UserRole.REBATE_ACCOUNTANT.value)


def make_contract_auditor_headers(user_id: str = AUDITOR_USER_ID):
    return build_user_headers(user_id, UserRole.CONTRACT_AUDITOR.value)


def make_operator_buyer_headers(operator_id: str):
    """X-User-ID must be the id of the Operator the buyer acts for."""
    return build_user_headers(operator_id, UserRole.OPERATOR_BUYER.value)


def make_manufacturer_rep_headers(manufacturer_id: str):
    """X-User-ID must be the id of the Manufacturer the rep acts for."""
    return build_user_headers(manufacturer_id, UserRole.MANUFACTURER_REP.value)


def make_headers_for_role(role: str, user_id: str):
    """Headers for an arbitrary role string, including unknown role values."""
    return build_user_headers(user_id, role)


# --------------------------------------------------------------------------
# Shared constants for the opaque roles
# --------------------------------------------------------------------------

TEST_USERS = {
    "system_admin": make_system_admin_headers(),
    "national_account_manager": make_national_account_manager_headers(),
    "pricing_analyst": make_pricing_analyst_headers(),
    "rebate_accountant": make_rebate_accountant_headers(),
    "contract_auditor": make_contract_auditor_headers(),
}

NO_AUTH_HEADERS = {"Content-Type": "application/json"}
