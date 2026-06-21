"""Pre-built role headers for every role in the PRD (PRD §2.1).

Per PRD §2.1 the `Cardholder` role is entity-backed: when `X-User-Role` is
`Cardholder`, `X-User-ID` is the `id` of the acting `CardAccount`, and any
ownership check compares the resource's `card_account_id` to `X-User-ID`. For
any ownership-gated call, callers MUST use `make_cardholder_headers(account_id)`
with a real `CardAccount.id` — the shared `TEST_USERS["cardholder_headers"]`
constant carries a placeholder user-id that never equals a real account UUID and
would be rejected with `ERR_NOT_ACCOUNT_OWNER`.

The other two roles (`ProgramAdmin`, `RewardsOps`) are opaque per PRD §2.1; the
shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form (PRD §2.1).
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "rewards_ops_headers": build_user_headers("test-rewards-ops-1", "RewardsOps"),
    # Entity-backed role — shared constant is a fallback for non-ownership
    # negative paths (401/403/404). Real ownership-gated calls must use
    # make_cardholder_headers(account["id"]).
    "cardholder_headers": build_user_headers("test-cardholder-1", "Cardholder"),
}


def make_cardholder_headers(account_id: str) -> dict:
    """Headers for a Cardholder bound to a specific CardAccount.id (PRD §2.1)."""
    return build_user_headers(account_id, "Cardholder")


def make_program_admin_headers(user_id: str = "test-program-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_rewards_ops_headers(user_id: str = "test-rewards-ops-1") -> dict:
    return build_user_headers(user_id, "RewardsOps")


def make_headers(user_id: str, role: str) -> dict:
    """Generic constructor for parametrized RBAC tests."""
    return build_user_headers(user_id, role)
