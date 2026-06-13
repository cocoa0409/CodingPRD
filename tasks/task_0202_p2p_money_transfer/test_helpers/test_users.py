"""Pre-built role headers for every role in the PRD.

The roles are Anonymous, AccountHolder, ComplianceOfficer, and PlatformAdmin.
AccountHolder is entity_backed:Account — ownership-gated calls MUST use the
per-instance builder make_account_holder_headers(account_id) with the real
Account.id. ComplianceOfficer and PlatformAdmin are opaque operator identities.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "account_holder_headers": build_user_headers("test-account-holder-1", "AccountHolder"),
    # Anonymous is unauthenticated; the canonical form is empty headers.
    "anonymous_headers": {},
}


# Per-instance builders — required for the entity_backed AccountHolder role.
def make_account_holder_headers(account_id: str) -> dict:
    """For AccountHolder (entity_backed:Account). Pass the actual Account.id as
    account_id whenever the call is ownership-gated (transfers, withdrawals,
    funding sources, money-request and split actions, opening disputes)."""
    return build_user_headers(account_id, "AccountHolder")


def make_compliance_officer_headers(user_id: str = "test-officer-1") -> dict:
    """For ComplianceOfficer (opaque). The id is recorded as reviewer/resolver
    and compared only for segregation of duties — pass a value distinct from any
    party to the underlying transfer."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For PlatformAdmin (opaque). The id is never compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")
