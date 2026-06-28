"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Dispatcher, BillingAdmin, PlatformAdmin),
# and for tests that don't exercise entity_backed ownership.
TEST_USERS = {
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "account_holder_headers": build_user_headers("test-account-holder-1", "AccountHolder"),
    "crew_tech_headers": build_user_headers("test-crew-tech-1", "CrewTech"),
    # opaque roles: shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


# Per-instance builders — required for every entity_backed role.
def make_account_holder_headers(user_id: str) -> dict:
    """For AccountHolder (entity_backed:AccountHolder). Pass the actual AccountHolder.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AccountHolder")


def make_crew_tech_headers(user_id: str) -> dict:
    """For CrewTech (entity_backed:Crew). Pass the actual Crew.id as user_id whenever the
    call is ownership-gated (completion checks the acting Crew.id against the route's crew)."""
    return build_user_headers(user_id, "CrewTech")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "Dispatcher")


def make_billing_admin_headers(user_id: str = "test-billing-admin-1") -> dict:
    """BillingAdmin is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "BillingAdmin")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """PlatformAdmin is opaque; user_id is not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")
