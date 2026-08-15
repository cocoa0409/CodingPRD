"""Pre-built role headers for every role in the PRD (section 2.1).

Subscriber is entity-backed by Account: ownership-gated calls must use
``make_subscriber_headers(account_id)`` with the real account id. The three
opaque roles (SupportAgent, PartnerBillingOps, PlatformAdmin) use shared
constants because the server never compares their X-User-ID to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role — shared constant only for non-ownership tests
    # (e.g. 403-on-forbidden-endpoint checks where the call must fail
    # before any ownership comparison matters).
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
    # Opaque roles — shared constants are the canonical form.
    "support_agent_headers": build_user_headers("test-support-1", "SupportAgent"),
    "partner_billing_ops_headers": build_user_headers(
        "test-partner-ops-1", "PartnerBillingOps"
    ),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_subscriber_headers(account_id: str) -> dict:
    """For Subscriber (entity-backed by Account). Pass the real account_id
    whenever the call is ownership-gated (own profile/subscription/save-offer)."""
    return build_user_headers(account_id, "Subscriber")


def make_support_agent_headers(user_id: str = "test-support-1") -> dict:
    return build_user_headers(user_id, "SupportAgent")


def make_partner_billing_ops_headers(user_id: str = "test-partner-ops-1") -> dict:
    return build_user_headers(user_id, "PartnerBillingOps")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
