"""Pre-built role headers for every role in the PRD.

RightsManager, FinanceAnalyst, and FinanceController are opaque identities:
X-User-ID is not tied to any persisted entity. PlatformBuyer is entity-backed
by Platform (X-User-ID is the acting Platform's id); ownership-gated calls
(accept/decline packages, submit revenue reports, buyer-visible reads) MUST
use make_platform_buyer_headers() with the real Platform.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "rights_manager_headers": build_user_headers("test-rm-1", "RightsManager"),
    "finance_analyst_headers": build_user_headers("test-fin-ana-1", "FinanceAnalyst"),
    "finance_controller_headers": build_user_headers("test-fin-ctl-1", "FinanceController"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "platform_buyer_headers": build_user_headers("test-buyer-1", "PlatformBuyer"),
}


def make_rights_manager_headers(user_id: str = "test-rm-1") -> dict:
    return build_user_headers(user_id, "RightsManager")


def make_finance_analyst_headers(user_id: str = "test-fin-ana-1") -> dict:
    return build_user_headers(user_id, "FinanceAnalyst")


def make_finance_controller_headers(user_id: str = "test-fin-ctl-1") -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_platform_buyer_headers(platform_id: str) -> dict:
    """For PlatformBuyer (entity_backed:Platform). Pass the acting Platform.id
    whenever the call is ownership-gated."""
    return build_user_headers(platform_id, "PlatformBuyer")
