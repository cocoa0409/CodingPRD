"""Pre-built role headers for every role in the PRD.

Every role uses an OPAQUE operator identity: the X-User-ID is never compared to
any entity id. The shared TEST_USERS constants are the canonical form for most
tests. The per-role builders exist for the separation-of-duties rule, where the
SAME X-User-ID that graded an item must (or must not) be the one acting on its
authentication review — those tests need to control the exact operator id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles, safe for any test that does not need to pin a
# specific operator id.
TEST_USERS = {
    "store_admin_headers": build_user_headers("op-store-admin-1", "StoreAdmin"),
    "intake_grader_headers": build_user_headers("op-intake-grader-1", "IntakeGrader"),
    "authenticator_headers": build_user_headers("op-authenticator-1", "Authenticator"),
    "cashier_clerk_headers": build_user_headers("op-cashier-clerk-1", "CashierClerk"),
    "settlement_manager_headers": build_user_headers("op-settlement-manager-1", "SettlementManager"),
}


# Per-role builders — pass an explicit operator id when a test must pin the
# acting X-User-ID (separation-of-duties scenarios).
def make_store_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StoreAdmin")


def make_intake_grader_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeGrader")


def make_authenticator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Authenticator")


def make_cashier_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CashierClerk")


def make_settlement_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SettlementManager")
