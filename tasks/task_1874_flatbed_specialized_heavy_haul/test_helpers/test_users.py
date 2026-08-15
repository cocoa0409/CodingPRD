"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Shipper tests that do not
# exercise ownership (the entity_backed Shipper role has per-instance builders
# below for ownership-gated calls).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed:Customer — fallback for non-ownership tests only.
    "shipper_headers": build_user_headers("test-shipper-1", "Shipper"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "permit_clerk_headers": build_user_headers("test-permit-clerk-1", "PermitClerk"),
    "state_authority_headers": build_user_headers("test-state-authority-1", "StateAuthority"),
    "safety_manager_headers": build_user_headers("test-safety-manager-1", "SafetyManager"),
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "billing_clerk_headers": build_user_headers("test-billing-clerk-1", "BillingClerk"),
}


def make_shipper_headers(user_id: str) -> dict:
    """For Shipper (entity_backed:Customer, PRD §2.1). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Shipper")
