"""Pre-built role headers for every role in the PRD (§2.1).

`OpsAdmin`, `ProcessAuthority`, and `QAReviewer` are opaque roles: X-User-ID is
an operator identifier never compared to an entity id, so the shared constants
are canonical; per-call builders exist so segregation-of-duties tests can pin a
specific X-User-ID. `Customer` is entity-backed by CustomerAccount: any
ownership-gated call MUST use make_customer_headers(customer["id"]) so that
X-User-ID equals the owning account's id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "ops_admin_headers": build_user_headers("ops-1", "OpsAdmin"),
    "qa_reviewer_headers": build_user_headers("qa-1", "QAReviewer"),
    "process_authority_headers": build_user_headers("pa-1", "ProcessAuthority"),
    # entity_backed:CustomerAccount — fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:CustomerAccount). Pass the actual
    CustomerAccount id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_ops_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OpsAdmin")


def make_qa_reviewer_headers(user_id: str) -> dict:
    """Pin a specific QA reviewer identity (segregation-of-duties tests)."""
    return build_user_headers(user_id, "QAReviewer")


def make_process_authority_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProcessAuthority")
