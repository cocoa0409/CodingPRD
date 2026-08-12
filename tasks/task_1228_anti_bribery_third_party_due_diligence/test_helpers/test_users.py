"""Pre-built role headers for every role in the PRD (§2.1).

All six roles carry an opaque operator identifier: the server never compares
X-User-ID against any resource's `id`; ownership and segregation-of-duties
checks compare recorded fields (sponsor_user_id, submitted_by_user_id,
approved_by_user_id, escalated_by_user_id, assignee_user_id) against the
caller's X-User-ID. Per-user builders below exist so tests can thread the
exact operator identity a scenario needs.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids used across scenarios.
ADMIN_ID = "u_admin1"
SPONSOR_1_ID = "u_sp1"
SPONSOR_2_ID = "u_sp2"
SPONSOR_9_ID = "u_sp9"
OFFICER_1_ID = "u_co1"
OFFICER_2_ID = "u_co2"
ANALYST_ID = "u_sa1"
FINANCE_1_ID = "u_fin1"
FINANCE_2_ID = "u_fin2"
AUDIT_LEAD_ID = "u_au1"


def admin_headers(user_id: str = ADMIN_ID) -> dict:
    return build_user_headers(user_id, "ComplianceAdmin")


def sponsor_headers(user_id: str = SPONSOR_1_ID) -> dict:
    return build_user_headers(user_id, "BusinessSponsor")


def analyst_headers(user_id: str = ANALYST_ID) -> dict:
    return build_user_headers(user_id, "ScreeningAnalyst")


def officer_headers(user_id: str = OFFICER_1_ID) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def finance_headers(user_id: str = FINANCE_1_ID) -> dict:
    return build_user_headers(user_id, "FinanceReviewer")


def audit_headers(user_id: str = AUDIT_LEAD_ID) -> dict:
    return build_user_headers(user_id, "AuditLead")


# Shared constants for the canonical operator of each role.
TEST_USERS = {
    "admin_headers": admin_headers(),
    "sponsor_headers": sponsor_headers(),
    "sponsor2_headers": sponsor_headers(SPONSOR_2_ID),
    "sponsor9_headers": sponsor_headers(SPONSOR_9_ID),
    "analyst_headers": analyst_headers(),
    "officer_headers": officer_headers(),
    "officer2_headers": officer_headers(OFFICER_2_ID),
    "finance_headers": finance_headers(),
    "finance2_headers": finance_headers(FINANCE_2_ID),
    "audit_headers": audit_headers(),
}
