"""Pre-built role headers for every role in the PRD.

All five roles use opaque X-User-ID identifiers (the PRD: "For all five roles,
`X-User-ID` is an opaque operator identifier not tied to any persisted
entity"), so shared constants are canonical. The per-instance builders exist
for segregation-of-duties scenarios, where a specific X-User-ID must match (or
differ from) the recorded originator id on a resource.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical shared user ids per role.
GIFT_OFFICER_USER_ID = "officer-1"
GIFT_ADMIN_USER_ID = "admin-1"
COMPLIANCE_USER_ID = "co-1"
ESTATE_MANAGER_USER_ID = "em-1"
FINANCE_STEWARD_USER_ID = "fs-1"

TEST_USERS = {
    "gift_officer_headers": build_user_headers(GIFT_OFFICER_USER_ID, "GiftOfficer"),
    "gift_admin_headers": build_user_headers(GIFT_ADMIN_USER_ID, "GiftAdministrator"),
    "compliance_headers": build_user_headers(COMPLIANCE_USER_ID, "ComplianceOfficer"),
    "estate_manager_headers": build_user_headers(ESTATE_MANAGER_USER_ID, "EstateManager"),
    "finance_steward_headers": build_user_headers(FINANCE_STEWARD_USER_ID, "FinanceSteward"),
}


def make_gift_officer_headers(user_id: str) -> dict:
    """GiftOfficer headers with a specific X-User-ID (SoD scenarios)."""
    return build_user_headers(user_id, "GiftOfficer")


def make_gift_admin_headers(user_id: str) -> dict:
    """GiftAdministrator headers with a specific X-User-ID (SoD scenarios)."""
    return build_user_headers(user_id, "GiftAdministrator")


def make_compliance_headers(user_id: str) -> dict:
    """ComplianceOfficer headers with a specific X-User-ID (SoD scenarios)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_estate_manager_headers(user_id: str) -> dict:
    """EstateManager headers with a specific X-User-ID (SoD scenarios)."""
    return build_user_headers(user_id, "EstateManager")


def make_finance_steward_headers(user_id: str) -> dict:
    """FinanceSteward headers with a specific X-User-ID."""
    return build_user_headers(user_id, "FinanceSteward")
