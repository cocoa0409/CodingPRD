"""Pre-built role headers for every role in the PRD.

Member is entity_backed: `X-User-ID` must equal the acting member's `id` for
ownership-gated calls. ConciergeAgent / AccountManager / FinanceOps are opaque:
their `X-User-ID` is never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Member tests that do NOT
# exercise ownership (e.g. 401/403/404 paths). Owner-gated success paths MUST
# use make_member_headers(member_id).
TEST_USERS = {
    "member_headers": build_user_headers("member-shared", "Member"),
    "concierge_agent_headers": build_user_headers("agent-1", "ConciergeAgent"),
    "account_manager_headers": build_user_headers("manager-1", "AccountManager"),
    "finance_ops_headers": build_user_headers("finance-1", "FinanceOps"),
}


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as X-User-ID so
    the ownership check (membership.member_id == X-User-ID) passes."""
    return build_user_headers(member_id, "Member")


def make_concierge_agent_headers(user_id: str = "agent-1") -> dict:
    """Opaque ConciergeAgent identity."""
    return build_user_headers(user_id, "ConciergeAgent")


def make_account_manager_headers(user_id: str = "manager-1") -> dict:
    """Opaque AccountManager identity."""
    return build_user_headers(user_id, "AccountManager")


def make_finance_ops_headers(user_id: str = "finance-1") -> dict:
    """Opaque FinanceOps identity."""
    return build_user_headers(user_id, "FinanceOps")
