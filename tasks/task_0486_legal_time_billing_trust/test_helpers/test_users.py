"""Pre-built role headers for every role in the PRD (§2.1).

All three roles (PlatformAdmin, BillingClerk, Attorney) carry an OPAQUE identity:
the X-User-ID is an opaque operator string never tied to a persisted entity and
never compared against any resource id. So the shared constants are the canonical
form everywhere; the per-actor builders exist only to control the X-User-ID value
that gets recorded as initiated_by/approved_by on a trust transaction (for the
segregation-of-duties comparison).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for every test (all roles are opaque).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "billing_clerk_headers": build_user_headers("clerk-1", "BillingClerk"),
    "attorney_headers": build_user_headers("att-9", "Attorney"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers with a chosen opaque X-User-ID."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_billing_clerk_headers(user_id: str) -> dict:
    """BillingClerk headers with a chosen opaque X-User-ID.

    Use when the test needs to control which operator string is recorded as a
    trust transaction's initiated_by_user_id, or as the actor in an SoD check.
    """
    return build_user_headers(user_id, "BillingClerk")


def make_attorney_headers(user_id: str) -> dict:
    """Attorney headers with a chosen opaque X-User-ID.

    Use to control the approver/reverser X-User-ID for segregation-of-duties.
    """
    return build_user_headers(user_id, "Attorney")
