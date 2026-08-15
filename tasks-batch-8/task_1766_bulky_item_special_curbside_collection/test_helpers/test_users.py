"""Pre-built role headers for every role in the PRD.

Resident is entity-backed by Household: X-User-ID must equal the acting
Household.id on any ownership-gated call, so the per-instance builder
make_resident_headers(household_id) is mandatory there. Driver, Inspector,
and Dispatcher are opaque identities; their shared constants are canonical.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (bad-payload, missing-resource, wrong-role checks).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    # opaque roles: shared constants are the canonical form.
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
}


def make_resident_headers(household_id: str) -> dict:
    """For Resident (entity_backed:Household). Pass the actual Household.id as
    household_id whenever the call is ownership-gated."""
    return build_user_headers(household_id, "Resident")


def make_driver_headers(user_id: str = "test-driver-1") -> dict:
    return build_user_headers(user_id, "Driver")


def make_inspector_headers(user_id: str = "test-inspector-1") -> dict:
    return build_user_headers(user_id, "Inspector")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")
