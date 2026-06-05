"""Pre-built role headers for every role in the PRD.

PRD §2.1: X-User-Role is one of BillingAdmin, AccountOwner, Anonymous.
For AccountOwner, X-User-ID must equal the acting Account.id (ownership is
compared against the resource's account FK), so ownership-gated calls MUST
use make_account_owner_headers(account_id) with the real account id.
BillingAdmin and Anonymous carry opaque ids not tied to any entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for AccountOwner tests that do
# NOT exercise ownership (e.g. 401/403/404/422 before the ownership check, or
# RBAC-denial tests where the role itself is rejected).
TEST_USERS = {
    "billing_admin_headers": build_user_headers("admin-operator-1", "BillingAdmin"),
    "anonymous_headers": build_user_headers("anon-registrant-1", "Anonymous"),
    # Fallback only — never use for an ownership-gated call against a real account.
    "account_owner_headers": build_user_headers("account-owner-fallback-1", "AccountOwner"),
}


def make_account_owner_headers(account_id: str) -> dict:
    """For AccountOwner (entity_backed:Account). Pass the real Account.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(account_id, "AccountOwner")
