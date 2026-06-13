"""Pre-built role headers for every role in the PRD (§2.1).

Per §2.1: for the three staff roles (SalesAssociate, Goldsmith, StoreManager)
the ``X-User-ID`` value is an opaque operator identifier not tied to any entity —
shared constants are the canonical form. For ``Customer``, ``X-User-ID`` is the
acting Customer record's ``id``; ownership checks compare ``customer_id`` to it, so
Customer requests MUST use the per-instance builder with the real customer id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque staff roles, and Customer fallback for non-ownership tests.
TEST_USERS = {
    "sales_associate_headers": build_user_headers("staff-sales-1", "SalesAssociate"),
    "goldsmith_headers": build_user_headers("staff-goldsmith-1", "Goldsmith"),
    "store_manager_headers": build_user_headers("staff-manager-1", "StoreManager"),
    # Fallback only; ownership-gated Customer calls must use make_customer_headers().
    "customer_headers": build_user_headers("customer-fallback-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Customer")
