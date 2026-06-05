"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatch-1", "DispatchManager"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "crew_headers": build_user_headers("test-crew-1", "CrewLead"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_crew_headers(user_id: str) -> dict:
    """For CrewLead (entity_backed:Crew). Pass the actual Crew.id as user_id
    whenever the call completes a visit dispatched to its route."""
    return build_user_headers(user_id, "CrewLead")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_dispatcher_headers(user_id: str = "test-dispatch-1") -> dict:
    return build_user_headers(user_id, "DispatchManager")


def make_unknown_role_headers(user_id: str = "nobody-1") -> dict:
    """An unrecognized role name; used for ERR_UNAUTHENTICATED tests."""
    return build_user_headers(user_id, "Nobody")
