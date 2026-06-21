"""Pre-built role headers for every role in the PRD.

All four roles (RevenueManager, GroupSalesManager, ChannelManager, Analyst)
carry an opaque identity (PRD §2.1): X-User-ID is never compared to any entity's
id, so a shared constant per role is the canonical form. No entity_backed roles
exist, so no per-instance header builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "revenue_manager_headers": build_user_headers("test-rm-1", "RevenueManager"),
    "group_sales_manager_headers": build_user_headers(
        "test-gsm-1", "GroupSalesManager"
    ),
    "channel_manager_headers": build_user_headers("test-cm-1", "ChannelManager"),
    "analyst_headers": build_user_headers("test-analyst-1", "Analyst"),
}

# Headers naming an unknown role — used to exercise ERR_UNAUTHENTICATED (PRD §2.1).
UNKNOWN_ROLE_HEADERS = build_user_headers("test-nobody-1", "Nobody")
