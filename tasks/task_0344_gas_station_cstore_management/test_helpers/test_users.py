"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # StationManager: opaque operator identifier, never compared to any entity id.
    "manager_headers": build_user_headers("mgr-1", "StationManager"),
    # CashierAttendant: opaque operator identifier; the server records it as
    # cashier_user_id when this cashier opens a shift. Default "cash1".
    "cashier_headers": build_user_headers("cash1", "CashierAttendant"),
    # A second cashier identity for non-owner shift-op tests.
    "cashier2_headers": build_user_headers("cash2", "CashierAttendant"),
}


def make_manager_headers(user_id: str = "mgr-1") -> dict:
    """StationManager (opaque). user_id is not tied to any entity."""
    return build_user_headers(user_id, "StationManager")


def make_cashier_headers(user_id: str = "cash1") -> dict:
    """CashierAttendant (opaque). The server stores this user_id as the shift's
    cashier_user_id, and compares it for owner-only shift ops (begin-count, close).
    Pass the SAME user_id that opened the shift for owner ops; a different one to
    test the non-owner path."""
    return build_user_headers(user_id, "CashierAttendant")


def make_loyalty_member_headers(loyalty_account_id: str) -> dict:
    """LoyaltyMember (entity_backed:LoyaltyAccount). Pass the actual LoyaltyAccount.id
    as user_id whenever the call is ownership-gated (e.g., redeeming own points)."""
    return build_user_headers(loyalty_account_id, "LoyaltyMember")
