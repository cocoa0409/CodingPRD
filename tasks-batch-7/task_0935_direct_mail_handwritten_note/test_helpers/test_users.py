"""Pre-built role headers for every role named in the PRD.

Five of the six roles carry an opaque operator identifier that the server never
compares to any entity id, so a shared constant is the canonical form for them.
``AccountOwner`` is the one identity-backed role: its ``X-User-ID`` is the id of
the acting ``Account``, so every ownership-gated call made as an AccountOwner
MUST use ``make_account_owner_headers(account["id"])``.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used throughout the suite.
ADMIN_USER_ID = "admin-1"
CAMPAIGN_MANAGER_USER_ID = "cm-1"
LIST_OPERATOR_USER_ID = "lo-1"
PRODUCTION_OPERATOR_USER_ID = "po-1"
COMPLIANCE_OFFICER_USER_ID = "co-1"

TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "campaign_manager_headers": build_user_headers(
        CAMPAIGN_MANAGER_USER_ID, "CampaignManager"
    ),
    "list_operator_headers": build_user_headers(LIST_OPERATOR_USER_ID, "ListOperator"),
    "production_operator_headers": build_user_headers(
        PRODUCTION_OPERATOR_USER_ID, "ProductionOperator"
    ),
    "compliance_officer_headers": build_user_headers(
        COMPLIANCE_OFFICER_USER_ID, "ComplianceOfficer"
    ),
    # Fallback only for tests that never exercise account scope (for example a
    # 401 on a missing header).  Ownership-gated calls must use the builder.
    "account_owner_headers": build_user_headers("test-account-owner", "AccountOwner"),
}

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
CAMPAIGN_MANAGER = TEST_USERS["campaign_manager_headers"]
LIST_OPERATOR = TEST_USERS["list_operator_headers"]
PRODUCTION_OPERATOR = TEST_USERS["production_operator_headers"]
COMPLIANCE_OFFICER = TEST_USERS["compliance_officer_headers"]


def make_account_owner_headers(account_id: str) -> dict:
    """Headers for AccountOwner acting as the Account whose id is ``account_id``."""
    return build_user_headers(account_id, "AccountOwner")


def headers_for(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/identifier pair.

    Used where the identifier itself is under test -- for example the
    segregation-of-duties rule, which compares the approving caller's
    ``X-User-ID`` against the identifier recorded at submission.
    """
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers carrying an identifier but no ``X-User-Role`` at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> dict:
    """Headers naming a role but carrying no ``X-User-ID`` at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
