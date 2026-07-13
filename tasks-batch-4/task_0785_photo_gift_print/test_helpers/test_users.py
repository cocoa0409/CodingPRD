"""Pre-built role headers for every role in the PRD.

CatalogAdmin and ProductionOperator are opaque roles (X-User-ID is an opaque
operator identifier, never compared to any entity id) — the shared constants are
their canonical form.

Customer is entity-backed: X-User-ID must equal the acting Customer's id for
ownership checks to pass. Use make_customer_headers(customer_id) with the real
customer id whenever a call is ownership-gated. The shared TEST_USERS entry is a
fallback for non-ownership tests only.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "catalog_admin_headers": build_user_headers("test-admin-1", "CatalogAdmin"),
    "production_operator_headers": build_user_headers("test-operator-1", "ProductionOperator"),
    # Entity-backed Customer — fallback only (never for ownership-gated calls).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "CatalogAdmin")


def make_operator_headers(user_id: str = "test-operator-1") -> dict:
    return build_user_headers(user_id, "ProductionOperator")
