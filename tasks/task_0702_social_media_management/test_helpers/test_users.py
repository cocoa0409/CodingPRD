"""Pre-built role headers for every role in the PRD.

Every role uses an opaque identity model: X-User-ID is an opaque operator
identifier never compared to any entity's id. So the shared constants below
are the canonical form for all roles; there are no ownership-gated builders.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "account_manager_headers": build_user_headers("am-1", "AccountManager"),
    "content_creator_headers": build_user_headers("cc-1", "ContentCreator"),
    "approver_headers": build_user_headers("ap-1", "Approver"),
    "community_agent_headers": build_user_headers("ca-1", "CommunityAgent"),
    "finance_controller_headers": build_user_headers("fc-1", "FinanceController"),
    "platform_admin_headers": build_user_headers("pa-1", "PlatformAdmin"),
}
