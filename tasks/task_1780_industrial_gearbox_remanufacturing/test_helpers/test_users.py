"""Pre-built role headers for every role in the PRD (§2.1).

IntakeCoordinator, RemanEngineer, QualityInspector, and ServiceManager are
opaque identities: X-User-ID is not tied to any persisted entity. Customer is
entity-backed by Customer: X-User-ID is the acting Customer entity's id, so
ownership-gated calls MUST use make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "intake_coordinator_headers": build_user_headers(
        "test-intake-coordinator-1", "IntakeCoordinator"),
    "reman_engineer_headers": build_user_headers(
        "test-reman-engineer-1", "RemanEngineer"),
    "quality_inspector_headers": build_user_headers(
        "test-quality-inspector-1", "QualityInspector"),
    "service_manager_headers": build_user_headers(
        "test-service-manager-1", "ServiceManager"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (its X-User-ID equals no real Customer id).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_intake_coordinator_headers(user_id: str = "test-intake-coordinator-1") -> dict:
    return build_user_headers(user_id, "IntakeCoordinator")


def make_reman_engineer_headers(user_id: str = "test-reman-engineer-1") -> dict:
    return build_user_headers(user_id, "RemanEngineer")


def make_quality_inspector_headers(user_id: str = "test-quality-inspector-1") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def make_service_manager_headers(user_id: str = "test-service-manager-1") -> dict:
    return build_user_headers(user_id, "ServiceManager")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id
    whenever the call is ownership-gated (approve-scope, warranty-claims,
    cancel from SCOPE_APPROVAL, own-record reads)."""
    return build_user_headers(customer_id, "Customer")
