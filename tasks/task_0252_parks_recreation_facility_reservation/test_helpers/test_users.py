"""Pre-built role headers for every role in the PRD.

Per PRD §2.1, every request carries X-User-ID and X-User-Role. For a Patron,
X-User-ID is the acting Patron's id and ownership checks compare it to the
targeted resource's owning patron_id. For RecCoordinator and FinanceClerk,
X-User-ID is an opaque operator identifier not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
# - RecCoordinator and FinanceClerk are opaque: the shared constant is canonical.
# - The Patron shared constant is a fallback for tests that do NOT exercise
#   ownership (e.g. reads, 401/403/404 paths). Ownership-gated Patron calls must
#   use make_patron_headers(<actual Patron.id>).
TEST_USERS = {
    "rec_coordinator_headers": build_user_headers("op-coordinator-1", "RecCoordinator"),
    "finance_clerk_headers": build_user_headers("op-finance-1", "FinanceClerk"),
    "patron_headers": build_user_headers("any-patron", "Patron"),
}


def make_patron_headers(user_id: str) -> dict:
    """Headers for a Patron (entity_backed:Patron). Pass the actual Patron.id as
    user_id whenever the call is ownership-gated (apply, cancel, withdraw, COI
    create, lottery entry on own behalf)."""
    return build_user_headers(user_id, "Patron")


def make_coordinator_headers(user_id: str = "op-coordinator-1") -> dict:
    return build_user_headers(user_id, "RecCoordinator")


def make_finance_headers(user_id: str = "op-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceClerk")
