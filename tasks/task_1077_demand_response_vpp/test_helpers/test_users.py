"""Pre-built role headers for every role in the PRD.

Two roles are entity-backed (Aggregator, Customer): their X-User-ID must be the
id of a real persisted entity, so ownership-gated calls MUST use the
make_*_headers(entity_id) builders. ProgramOperator and Auditor are opaque and
use shared constants. The ProgramOperator id additionally matters only where a
transition records it (dispatched_by_user_id on notify, approved_by_user_id on
approve) — segregation-of-duties tests thread distinct operator ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (ProgramOperator, Auditor) and for
# negative tests (401/403/404/422) whose success does not depend on ownership.
TEST_USERS = {
    # Default operator; also the canonical "op1" dispatcher in fixtures.
    "program_operator_headers": build_user_headers("op1", "ProgramOperator"),
    # A distinct operator used as the settlement approver (SoD-clean path).
    "second_operator_headers": build_user_headers("op2", "ProgramOperator"),
    "auditor_headers": build_user_headers("aud1", "Auditor"),
    # entity-backed fallbacks (NOT for ownership-gated calls):
    "aggregator_headers": build_user_headers("test-aggregator-1", "Aggregator"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_operator_headers(user_id: str) -> dict:
    """ProgramOperator is opaque; pass an explicit operator id (e.g. op1/op2)."""
    return build_user_headers(user_id, "ProgramOperator")


def make_aggregator_headers(aggregator_id: str) -> dict:
    """For Aggregator (entity_backed:Aggregator). Pass the acting Aggregator.id."""
    return build_user_headers(aggregator_id, "Aggregator")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id."""
    return build_user_headers(customer_id, "Customer")


def operator_headers() -> dict:
    """Default opaque ProgramOperator credential (op1)."""
    return TEST_USERS["program_operator_headers"]


# A request with no auth headers (used for the 401 unauthenticated path).
ANON_HEADERS: dict = {"Content-Type": "application/json"}
