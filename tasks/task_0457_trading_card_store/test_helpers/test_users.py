"""Pre-built role headers for every role in the PRD.

Customer is entity-backed: ownership checks compare a resource's customer foreign
key to X-User-ID, so any ownership-gated call MUST use make_customer_headers with
the real Customer.id. StoreManager and JudgeStaff are opaque operator identities
whose X-User-ID is never own-checked.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (StoreManager, JudgeStaff) and for
# Customer-role tests that do not exercise ownership (e.g., 401/unknown-role).
TEST_USERS = {
    # entity_backed:Customer — shared constant is a fallback for NON-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles — shared constant is the canonical form.
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "judge_headers": build_user_headers("test-judge-1", "JudgeStaff"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (buylist, registration,
    pre-order, consignment, ledger, grading the customer owns)."""
    return build_user_headers(user_id, "Customer")


def make_store_manager_headers(user_id: str = "test-manager-1") -> dict:
    """StoreManager is opaque; X-User-ID is not own-checked."""
    return build_user_headers(user_id, "StoreManager")


def make_judge_headers(user_id: str = "test-judge-1") -> dict:
    """JudgeStaff is opaque; X-User-ID is not own-checked."""
    return build_user_headers(user_id, "JudgeStaff")
