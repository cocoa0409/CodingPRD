"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (DispatchSupervisor, YardManager,
# CitizenServices), and for Operator only in tests that do NOT exercise ownership
# (e.g. 400/404/403-unauthorized on a resource the operator does not own).
TEST_USERS = {
    "dispatch_headers": build_user_headers("test-dispatch-1", "DispatchSupervisor"),
    "yard_headers": build_user_headers("test-yard-1", "YardManager"),
    "citizen_headers": build_user_headers("test-citizen-1", "CitizenServices"),
    # Fallback operator identity for non-ownership tests only.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
}


def make_operator_headers(user_id: str) -> dict:
    """For the Operator role (entity_backed:Operator). Pass the actual Operator.id
    as user_id whenever the call is ownership-gated (applications, avl-ping,
    callout complete)."""
    return build_user_headers(user_id, "Operator")


def make_dispatch_headers(user_id: str = "test-dispatch-1") -> dict:
    return build_user_headers(user_id, "DispatchSupervisor")


def make_yard_headers(user_id: str = "test-yard-1") -> dict:
    return build_user_headers(user_id, "YardManager")


def make_citizen_headers(user_id: str = "test-citizen-1") -> dict:
    return build_user_headers(user_id, "CitizenServices")
