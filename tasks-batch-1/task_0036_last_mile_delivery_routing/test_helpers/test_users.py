"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "dispatch_manager_headers": build_user_headers("test-dispatch-1", "DispatchManager"),
    "sort_associate_headers": build_user_headers("test-sort-1", "SortAssociate"),
    "customer_service_agent_headers": build_user_headers("test-csa-1", "CustomerServiceAgent"),
    # entity_backed:Driver — shared constant is a fallback for non-ownership tests only.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
}


def make_driver_headers(user_id: str) -> dict:
    """For Driver (entity_backed:Driver). Pass the actual Driver.id as user_id
    whenever the call is ownership-gated (e.g. logging an attempt on a stop of
    that driver's route)."""
    return build_user_headers(user_id, "Driver")
