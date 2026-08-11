"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership-gated calls.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "depot_manager_headers": build_user_headers("test-depot-mgr-1", "DepotManager"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_clerk_1_headers": build_user_headers("clerk_1", "BillingClerk"),
    "billing_clerk_2_headers": build_user_headers("clerk_2", "BillingClerk"),
    "safety_officer_headers": build_user_headers("test-safety-1", "SafetyOfficer"),
    # Fallback for CustomerAgent calls that are not ownership-gated (e.g.
    # schema-validation probes). Ownership-gated calls MUST use
    # make_customer_agent_headers(customer_id) with the real Customer id.
    "customer_agent_headers": build_user_headers("test-agent-1", "CustomerAgent"),
}

# No auth headers at all — for ERR_UNAUTHENTICATED probes (PRD §2.1).
ANONYMOUS_HEADERS = {}


def make_platform_admin_headers(user_id="test-admin-1"):
    return build_user_headers(user_id, "PlatformAdmin")


def make_depot_manager_headers(user_id="test-depot-mgr-1"):
    return build_user_headers(user_id, "DepotManager")


def make_dispatcher_headers(user_id="test-dispatcher-1"):
    return build_user_headers(user_id, "Dispatcher")


def make_billing_clerk_headers(user_id):
    """BillingClerk is opaque; user_id distinguishes clerks for the billing
    segregation-of-duties rule (PRD §2.1/§3.8)."""
    return build_user_headers(user_id, "BillingClerk")


def make_safety_officer_headers(user_id="test-safety-1"):
    return build_user_headers(user_id, "SafetyOfficer")


def make_customer_agent_headers(user_id):
    """CustomerAgent is entity-backed (PRD §2.1): X-User-ID must equal the
    acting Customer's id for ownership-gated calls."""
    return build_user_headers(user_id, "CustomerAgent")
