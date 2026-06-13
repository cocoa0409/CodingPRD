"""Pre-built role headers for every role in the PRD.

Per PRD §2.1:
  - Customer: X-User-ID is the id of the acting Customer; ownership checks compare
    a resource's owning customer reference to X-User-ID. So Customer headers used on
    ownership-gated calls MUST carry the real Customer.id (use make_customer_headers).
  - LotOperator: X-User-ID is an opaque operator identifier, not tied to any entity.
  - FacilityAdmin: X-User-ID is likewise an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for Customer-tests that do NOT
# exercise ownership (e.g. forbidden-role checks where the role itself is rejected
# before any ownership comparison).
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constant is the canonical form.
    "lot_operator_headers": build_user_headers("test-operator-1", "LotOperator"),
    "facility_admin_headers": build_user_headers("test-admin-1", "FacilityAdmin"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    X-User-ID whenever the call is ownership-gated (book/cancel/assign-shuttle/
    register-vehicle/list-own)."""
    return build_user_headers(customer_id, "Customer")


def make_lot_operator_headers(user_id: str = "test-operator-1") -> dict:
    """For LotOperator (opaque). The id is recorded but never ownership-compared."""
    return build_user_headers(user_id, "LotOperator")


def make_facility_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For FacilityAdmin (opaque). The id is recorded but never ownership-compared."""
    return build_user_headers(user_id, "FacilityAdmin")
