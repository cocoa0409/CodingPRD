"""Pre-built role headers for every role in the PRD (§2.1).

All six roles are opaque: X-User-ID is never compared to an entity's id.
It IS recorded and compared user-to-user for segregation of duties (PRD §3.7)
and for the zone-clearance challenger check (PRD §3.9), so each role's shared
constant uses a distinct, stable user id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "booker_headers": build_user_headers("test-booker-1", "Booker"),
    "exhibitor_headers": build_user_headers("test-exhibitor-1", "Exhibitor"),
    "settlement_clerk_headers": build_user_headers("test-clerk-1", "SettlementClerk"),
    "marketing_lead_headers": build_user_headers("test-marketing-1", "MarketingLead"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_booker_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Booker")


def make_exhibitor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Exhibitor")


def make_settlement_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SettlementClerk")


def make_marketing_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MarketingLead")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
