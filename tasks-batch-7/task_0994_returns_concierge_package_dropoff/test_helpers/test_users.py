"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (SupportAgent, CarrierDispatcher,
# PlatformAdmin) whose X-User-ID is never compared to any entity id
# (PRD §2.1), and for entity-backed roles in tests that do not exercise an
# ownership check.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "platform_admin2_headers": build_user_headers("test-admin-2", "PlatformAdmin"),
    "support_agent_headers": build_user_headers("test-agent-1", "SupportAgent"),
    "support_agent2_headers": build_user_headers("test-agent-2", "SupportAgent"),
    "carrier_dispatcher_headers": build_user_headers(
        "test-dispatcher-1", "CarrierDispatcher"
    ),
    # Fallbacks for entity-backed roles: use ONLY where ownership is not exercised.
    "shopper_headers": build_user_headers("test-shopper-1", "Shopper"),
    "merchant_admin_headers": build_user_headers("test-merchant-1", "MerchantAdmin"),
    "location_operator_headers": build_user_headers("test-location-1", "LocationOperator"),
}


# Per-instance builders — required for entity-backed roles whenever the call is
# ownership-gated (PRD §2.1: X-User-ID must equal the acting entity's id).
def make_shopper_headers(shopper_id: str) -> dict:
    """Shopper role: X-User-ID must be the acting Shopper's id."""
    return build_user_headers(shopper_id, "Shopper")


def make_merchant_admin_headers(merchant_id: str) -> dict:
    """MerchantAdmin role: X-User-ID must be the acting MerchantAccount's id."""
    return build_user_headers(merchant_id, "MerchantAdmin")


def make_location_operator_headers(location_id: str) -> dict:
    """LocationOperator role: X-User-ID must be the acting DropoffLocation's id."""
    return build_user_headers(location_id, "LocationOperator")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin (opaque identity) with a caller-chosen X-User-ID.

    Needed where segregation of duties compares two opaque admin identities
    (billing close vs settle) — PRD §3.2.
    """
    return build_user_headers(user_id, "PlatformAdmin")


def make_support_agent_headers(user_id: str) -> dict:
    """SupportAgent (opaque identity) with a caller-chosen X-User-ID.

    Needed where segregation of duties compares exception opener vs resolver
    (PRD §3.9).
    """
    return build_user_headers(user_id, "SupportAgent")
