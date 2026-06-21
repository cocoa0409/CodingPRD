"""Pre-built role headers for every role in the PRD (§2.1).

Three of the four roles are opaque operators (Innkeeper, Housekeeper,
FinanceManager) whose X-User-ID is not tied to any persisted entity, so a shared
constant is the canonical form for them. The Guest role is entity_backed: a guest
acting on a booking must own it (Booking.guest_id == X-User-ID), so any
ownership-gated guest call MUST use make_guest_headers(guest["id"]) with the real
Guest entity id — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for the three opaque operator roles, and safe for
# Guest-role tests that do NOT exercise booking ownership (e.g. 401/403/404 paths
# or reads of inn-scoped resources).
TEST_USERS = {
    "innkeeper_headers": build_user_headers("test-innkeeper-1", "Innkeeper"),
    "housekeeper_headers": build_user_headers("test-housekeeper-1", "Housekeeper"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceManager"),
    # Guest shared constant: a fallback for non-ownership guest tests only. Its
    # X-User-ID is a string that equals no real Guest.id, so it must NOT be used
    # on ownership-gated booking actions.
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
}


# Per-instance builders --------------------------------------------------------
def make_innkeeper_headers(user_id: str = "test-innkeeper-1") -> dict:
    """Headers for an Innkeeper (opaque operator)."""
    return build_user_headers(user_id, "Innkeeper")


def make_housekeeper_headers(user_id: str = "test-housekeeper-1") -> dict:
    """Headers for a Housekeeper (opaque operator)."""
    return build_user_headers(user_id, "Housekeeper")


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    """Headers for a FinanceManager (opaque operator)."""
    return build_user_headers(user_id, "FinanceManager")


def make_guest_headers(user_id: str) -> dict:
    """For the Guest role (entity_backed:Guest). Pass the actual Guest.id as
    user_id whenever the call is ownership-gated (confirm/cancel/redeem-gift/
    refund-quote on the guest's own booking)."""
    return build_user_headers(user_id, "Guest")
