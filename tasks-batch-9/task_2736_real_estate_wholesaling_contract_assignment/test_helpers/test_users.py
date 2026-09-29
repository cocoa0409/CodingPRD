"""
Principal headers for the six roles.

Three of the six roles are backed by persisted entities, and for those roles
X-User-ID is a real foreign key rather than an audit string: a Wholesaler acts
as a Wholesaler.id, a Seller acts as a SellerLead.id, and a CashBuyer acts as a
CashBuyer.id. Those three therefore have no fixed constant — the caller passes
the entity identifier it just created to the matching builder.

The remaining three roles carry opaque identities the server records but never
compares to an entity's id, so fixed constants are correct for them.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# ---------------------------------------------------------------------------
# Opaque principals
# ---------------------------------------------------------------------------

PLATFORM_ADMIN_USER_ID = "pa-1"

TITLE_AGENT_1_USER_ID = "ta-1"
TITLE_AGENT_2_USER_ID = "ta-2"
TITLE_AGENT_ALPHA_USER_ID = "ta-alpha"
TITLE_AGENT_BETA_USER_ID = "ta-beta"

COMPLIANCE_OFFICER_1_USER_ID = "co-1"
COMPLIANCE_OFFICER_2_USER_ID = "co-2"
COMPLIANCE_OFFICER_ALPHA_USER_ID = "co-alpha"
COMPLIANCE_OFFICER_BETA_USER_ID = "co-beta"


# ---------------------------------------------------------------------------
# Per-role header builders
# ---------------------------------------------------------------------------


def make_wholesaler_headers(user_id: str) -> Dict[str, str]:
    """Headers for a Wholesaler principal; user_id is the Wholesaler's id."""
    return build_user_headers(user_id, Role.WHOLESALER)


def make_seller_headers(user_id: str) -> Dict[str, str]:
    """Headers for a Seller principal; user_id is the SellerLead's id."""
    return build_user_headers(user_id, Role.SELLER)


def make_cash_buyer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a CashBuyer principal; user_id is the CashBuyer's id."""
    return build_user_headers(user_id, Role.CASH_BUYER)


def make_title_agent_headers(user_id: str = TITLE_AGENT_1_USER_ID) -> Dict[str, str]:
    """Headers for a TitleAgent principal; user_id is an opaque operator id."""
    return build_user_headers(user_id, Role.TITLE_AGENT)


def make_compliance_officer_headers(
    user_id: str = COMPLIANCE_OFFICER_1_USER_ID,
) -> Dict[str, str]:
    """Headers for a ComplianceOfficer principal; user_id is opaque."""
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER)


def make_platform_admin_headers(
    user_id: str = PLATFORM_ADMIN_USER_ID,
) -> Dict[str, str]:
    """Headers for a PlatformAdmin principal; user_id is opaque."""
    return build_user_headers(user_id, Role.PLATFORM_ADMIN)


# ---------------------------------------------------------------------------
# Shared, ready-made header dicts for the opaque roles
# ---------------------------------------------------------------------------

PLATFORM_ADMIN = make_platform_admin_headers()

TITLE_AGENT_1 = make_title_agent_headers(TITLE_AGENT_1_USER_ID)
TITLE_AGENT_2 = make_title_agent_headers(TITLE_AGENT_2_USER_ID)
TITLE_AGENT_ALPHA = make_title_agent_headers(TITLE_AGENT_ALPHA_USER_ID)
TITLE_AGENT_BETA = make_title_agent_headers(TITLE_AGENT_BETA_USER_ID)

COMPLIANCE_OFFICER_1 = make_compliance_officer_headers(COMPLIANCE_OFFICER_1_USER_ID)
COMPLIANCE_OFFICER_2 = make_compliance_officer_headers(COMPLIANCE_OFFICER_2_USER_ID)
COMPLIANCE_OFFICER_ALPHA = make_compliance_officer_headers(
    COMPLIANCE_OFFICER_ALPHA_USER_ID
)
COMPLIANCE_OFFICER_BETA = make_compliance_officer_headers(
    COMPLIANCE_OFFICER_BETA_USER_ID
)

TEST_USERS = {
    "platform_admin": PLATFORM_ADMIN,
    "title_agent_1": TITLE_AGENT_1,
    "title_agent_2": TITLE_AGENT_2,
    "title_agent_alpha": TITLE_AGENT_ALPHA,
    "title_agent_beta": TITLE_AGENT_BETA,
    "compliance_officer_1": COMPLIANCE_OFFICER_1,
    "compliance_officer_2": COMPLIANCE_OFFICER_2,
    "compliance_officer_alpha": COMPLIANCE_OFFICER_ALPHA,
    "compliance_officer_beta": COMPLIANCE_OFFICER_BETA,
}
