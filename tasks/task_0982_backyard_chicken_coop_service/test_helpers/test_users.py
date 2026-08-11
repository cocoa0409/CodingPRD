"""Pre-built role headers for every role in the PRD (§2.1).

Customer is bound to a HouseholdAccount id: for ownership-gated calls,
ALWAYS build headers with make_customer_headers(household["id"]) — the shared
constant carries a placeholder id that owns nothing. ServiceTech is opaque but
technician-scoped actions compare X-User-ID to assigned_technician_id /
route technician_id, so use make_service_tech_headers(technician_id) there.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Shared constants — safe for opaque roles and for calls whose success
    # does not depend on owning the subject resource.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "service_tech_headers": build_user_headers("test-tech-1", "ServiceTech"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_admin_headers": build_user_headers("test-billing-1", "BillingAdmin"),
    "platform_admin_headers": build_user_headers("test-platform-1", "PlatformAdmin"),
}


def make_customer_headers(household_id: str) -> dict:
    """Customer headers whose X-User-ID is the acting HouseholdAccount id."""
    return build_user_headers(household_id, "Customer")


def make_service_tech_headers(technician_id: str) -> dict:
    """ServiceTech headers whose X-User-ID is the recorded technician id."""
    return build_user_headers(technician_id, "ServiceTech")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_billing_admin_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingAdmin")


def make_platform_admin_headers(user_id: str = "test-platform-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
