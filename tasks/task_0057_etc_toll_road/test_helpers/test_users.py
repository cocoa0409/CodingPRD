"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for AccountHolder tests that don't
# exercise ownership (400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    # AccountHolder is entity_backed:Account — this shared constant is only a fallback
    # for non-ownership tests. Ownership-gated calls MUST use make_account_holder_headers.
    "account_holder_headers": build_user_headers("test-account-holder-1", "AccountHolder"),
    # opaque roles: shared constant is the canonical form.
    "toll_operator_headers": build_user_headers("test-toll-operator-1", "TollOperator"),
    "interop_clerk_headers": build_user_headers("test-interop-clerk-1", "InteropClerk"),
    "system_admin_headers": build_user_headers("test-system-admin-1", "SystemAdmin"),
}


def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity_backed:Account). Pass the actual Account.id as the
    acting principal whenever the call is ownership-gated (PRD §2.1: X-User-ID is the
    id of the acting Account; ownership checks compare the resource's owning-account
    foreign key to X-User-ID)."""
    return build_user_headers(account_id, "AccountHolder")
