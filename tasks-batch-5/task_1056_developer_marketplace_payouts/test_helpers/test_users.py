"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the five roles whose X-User-ID is an opaque
# operator identifier, and for Developer-role calls that do not exercise
# ownership (those must use make_developer_headers instead).
TEST_USERS = {
    "developer_headers": build_user_headers("test-developer-1", "Developer"),
    "review_agent_headers": build_user_headers("agent-1", "ReviewAgent"),
    "policy_officer_headers": build_user_headers("officer-1", "PolicyOfficer"),
    "policy_officer_opener_headers": build_user_headers("officer-open", "PolicyOfficer"),
    "policy_officer_decider_headers": build_user_headers("officer-decide", "PolicyOfficer"),
    "finance_ops_headers": build_user_headers("fin-1", "FinanceOps"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "storefront_headers": build_user_headers("storefront-1", "StorefrontService"),
}

# A request that carries neither X-User-ID nor X-User-Role.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}


def make_developer_headers(developer_id: str) -> dict:
    """Headers for the Developer role, whose X-User-ID is the acting
    Developer record's own id. Every ownership-gated call must use this."""
    return build_user_headers(developer_id, "Developer")


def make_review_agent_headers(user_id: str = "agent-1") -> dict:
    return build_user_headers(user_id, "ReviewAgent")


def make_policy_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PolicyOfficer")


def make_finance_ops_headers(user_id: str = "fin-1") -> dict:
    return build_user_headers(user_id, "FinanceOps")


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_storefront_headers(user_id: str = "storefront-1") -> dict:
    return build_user_headers(user_id, "StorefrontService")
