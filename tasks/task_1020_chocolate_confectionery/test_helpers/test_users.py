"""Pre-built role headers for every role the PRD recognises (PRD §2.1).

The PRD recognises exactly four roles. Three of them — ``SalesManager``,
``ProductionManager``, ``Admin`` — are opaque operator identifiers: the server
treats ``X-User-ID`` as an operator label and never compares it against any
entity id, so the shared constants below are the canonical form for those roles.

The ``Customer`` role is entity-backed: ``X-User-ID`` must equal the ``id`` of
the acting ``Customer`` record, and every ownership check on an Order,
CustomOrder, or Subscription compares that id. Any Customer-role call that must
pass an ownership check MUST use ``make_customer_headers(customer_id)`` with the
real customer's id; falling back to the shared constant reproduces the canonical
bug where every ownership check rejects every request.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque-identity roles — shared constants are the canonical form.
    "sales_manager_headers": build_user_headers("sales-manager-test-1", "SalesManager"),
    "production_manager_headers": build_user_headers(
        "production-manager-test-1", "ProductionManager"
    ),
    "admin_headers": build_user_headers("admin-test-1", "Admin"),
    # Customer fallback — used only for non-ownership tests (e.g. forbidden-role
    # or not-found rejections) where the literal X-User-ID need not match a real
    # customer id.
    "customer_headers": build_user_headers("customer-test-fallback", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer-role calls whose success depends on the caller owning the
    resource (PRD §2.1: ``X-User-ID`` is the acting Customer's id). Pass the
    customer's id so the ownership check passes."""
    return build_user_headers(customer_id, "Customer")
