"""Pre-built role headers for every role in the PRD.

Three roles (Dispatcher, HealthInspector, PlatformAdmin) carry opaque identities, so a
shared constant is the canonical form for them. The OperatorTruck role is entity_backed:
its X-User-ID must be the acting truck's id, so ownership-gated calls MUST use the
per-instance builder make_operator_truck_headers(truck_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - The three opaque roles use their shared constant everywhere.
#  - The OperatorTruck shared constant is a fallback for non-ownership tests only
#    (e.g. a 404-on-missing-resource probe); ownership-gated calls must use the builder.
TEST_USERS = {
    "operator_truck_headers": build_user_headers("test-operator-truck-1", "OperatorTruck"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "health_inspector_headers": build_user_headers("test-health-inspector-1", "HealthInspector"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_operator_truck_headers(truck_id: str) -> dict:
    """For the OperatorTruck role (entity_backed:OperatorTruck). Pass the actual
    OperatorTruck.id as X-User-ID whenever the call is ownership-gated — every write
    on a truck-owned resource compares the resource's truck_id to X-User-ID."""
    return build_user_headers(truck_id, "OperatorTruck")
