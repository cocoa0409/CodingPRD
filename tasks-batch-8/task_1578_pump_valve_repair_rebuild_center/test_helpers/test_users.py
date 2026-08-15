"""Pre-built role headers for every role in the PRD (§2.1).

The Customer role is entity-backed: when a call is ownership-gated (quote
approve / request-revision / decline, own-order intake or cancel, own-pool
withdraw), headers MUST be built from the real Customer.id via
make_customer_headers(customer_id). The shared "customer_headers" constant is
a fallback for tests that do not exercise ownership.

Staff roles are opaque: X-User-ID is not tied to any persisted entity, but it
is recorded by workflows (inspector_id, assembled_by_id, tested_by_id,
certified_by_id), so per-instance builders exist to thread stable operator ids
where segregation-of-duties comparisons depend on them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "service_manager_headers": build_user_headers("svc-mgr-1", "ServiceManager"),
    "intake_coordinator_headers": build_user_headers("intake-1", "IntakeCoordinator"),
    "inspector_headers": build_user_headers("inspector-1", "Inspector"),
    "technician_headers": build_user_headers("tech-1", "Technician"),
    "certifier_headers": build_user_headers("cert-1", "Certifier"),
    "planner_headers": build_user_headers("planner-1", "Planner"),
    # entity_backed: fallback only for non-ownership tests.
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_service_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceManager")


def make_intake_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Inspector")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (opaque). The id is recorded as assembled_by_id /
    tested_by_id, so SoD-sensitive setups thread a stable id."""
    return build_user_headers(user_id, "Technician")


def make_certifier_headers(user_id: str) -> dict:
    """For Certifier (opaque). The id is recorded as certified_by_id and must
    differ from the order's assembled_by_id (segregation of duties)."""
    return build_user_headers(user_id, "Certifier")


def make_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Planner")
