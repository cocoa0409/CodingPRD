"""Pre-built role headers for every role in the PRD.

Shopper is the sole entity_backed role — its X-User-ID must equal the acting
Customer's id for ownership-gated calls (placing/paying/cancelling an order,
converting a rental, creating fit profiles/subscriptions/returns, pausing/
resuming/cancelling a subscription). Use make_shopper_headers() with the real
Customer.id for those calls. The shared TEST_USERS["shopper_headers"] constant is
only safe for calls whose success does NOT depend on ownership (a 401/403 auth
denial, a 422 bad-payload, or a 404 missing-resource).

FulfillmentAgent, PlatformAdmin, and Guest are opaque roles; their shared
constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "shopper_headers": build_user_headers("test-shopper-shared-id", "Shopper"),
    # opaque roles: shared constant is the canonical form.
    "fulfillment_agent_headers": build_user_headers("test-fulfillment-agent", "FulfillmentAgent"),
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    "guest_headers": build_user_headers("test-guest", "Guest"),
    # Header carrying an unrecognized role, for ERR_UNAUTHENTICATED tests.
    "unknown_role_headers": build_user_headers("test-unknown", "Stranger"),
}


def make_shopper_headers(customer_id: str) -> dict:
    """For Shopper (entity_backed:Customer). Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated (every Shopper-owned write:
    order create/pay/cancel, rental convert, fit-profile/subscription/return
    create, subscription pause/resume/cancel)."""
    return build_user_headers(customer_id, "Shopper")


def make_fulfillment_agent_headers(user_id: str = "test-fulfillment-agent") -> dict:
    """FulfillmentAgent is opaque; user_id is never treated as a foreign key."""
    return build_user_headers(user_id, "FulfillmentAgent")


def make_platform_admin_headers(user_id: str = "test-platform-admin") -> dict:
    """PlatformAdmin is opaque; user_id is never treated as a foreign key."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_guest_headers(user_id: str = "test-guest") -> dict:
    """Guest is opaque; used for customer self-registration and public reads."""
    return build_user_headers(user_id, "Guest")
