"""Pre-built role headers for every role in the PRD.

All roles in this API use opaque operator identifiers: X-User-ID is never
compared against any entity id, so shared constants are safe everywhere.
Distinct user ids per role instance matter only where segregation-of-duties
checks compare two recorded operator ids (assessment author vs settlement
acceptor, appeal opener vs appeal decider).
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical operator ids used across fixtures.
ADMIN_USER_ID = "user-admin-1"
CLERK_USER_ID = "user-clerk-1"
ADJUSTER_USER_ID = "user-adjuster-1"
ADJUSTER_2_USER_ID = "user-adjuster-2"
MANAGER_USER_ID = "user-manager-1"
MANAGER_2_USER_ID = "user-manager-2"
SALVAGE_USER_ID = "user-salvage-1"
SUBRO_USER_ID = "user-subro-1"
FINANCE_USER_ID = "user-finance-1"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "clerk_headers": build_user_headers(CLERK_USER_ID, "ClaimsClerk"),
    "adjuster_headers": build_user_headers(ADJUSTER_USER_ID, "ClaimsAdjuster"),
    "adjuster2_headers": build_user_headers(ADJUSTER_2_USER_ID, "ClaimsAdjuster"),
    "manager_headers": build_user_headers(MANAGER_USER_ID, "ClaimsManager"),
    "manager2_headers": build_user_headers(MANAGER_2_USER_ID, "ClaimsManager"),
    "salvage_headers": build_user_headers(SALVAGE_USER_ID, "SalvageCoordinator"),
    "subro_headers": build_user_headers(SUBRO_USER_ID, "SubrogationSpecialist"),
    "finance_headers": build_user_headers(FINANCE_USER_ID, "FinanceController"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsClerk")


def make_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsManager")


def make_salvage_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalvageCoordinator")


def make_subro_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SubrogationSpecialist")


def make_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceController")
