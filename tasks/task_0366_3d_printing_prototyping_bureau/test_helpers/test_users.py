"""Pre-built role headers for every role in the PRD (§2.1).

Three of the four roles are `opaque` (BureauAdmin, Operator, QAReviewer): their
X-User-ID is not tied to any persisted entity, so the shared constant is the
canonical form. `Customer` is entity_backed: ownership checks compare the
resource's customer_id to X-User-ID, so ownership-gated calls MUST use the
per-instance builder make_customer_headers(customer_id), never the shared
constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - opaque roles: canonical form, used everywhere.
#  - customer: fallback for tests that do NOT exercise ownership (e.g. 404 on a
#    missing resource where the customer never owns anything).
TEST_USERS = {
    "bureau_admin_headers": build_user_headers("test-admin-1", "BureauAdmin"),
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "qa_reviewer_headers": build_user_headers("test-qa-1", "QAReviewer"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as the
    user id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(customer_id, "Customer")


def make_bureau_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "BureauAdmin")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    return build_user_headers(user_id, "Operator")


def make_qa_reviewer_headers(user_id: str = "test-qa-1") -> dict:
    return build_user_headers(user_id, "QAReviewer")
