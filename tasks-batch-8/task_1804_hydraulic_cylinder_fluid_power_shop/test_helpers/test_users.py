"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ShopAdmin, ServiceAdvisor, QualityInspector) use a shared constant:
the server does not compare their X-User-ID to any entity's id.

Entity-backed roles (Technician, Customer) MUST use the per-instance builders
with the actual entity id whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared constants.
    "shop_admin_headers": build_user_headers("admin-1", "ShopAdmin"),
    "service_advisor_headers": build_user_headers("advisor-1", "ServiceAdvisor"),
    "quality_inspector_headers": build_user_headers("insp-1", "QualityInspector"),
    # Entity-backed fallbacks — only for tests that do not exercise ownership.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity-backed). Pass the actual Technician.id whenever
    the call is ownership-gated (start-repair, complete-assembly, consume,
    dispatch, field complete, teardown filing/revision)."""
    return build_user_headers(user_id, "Technician")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed). Pass the actual Customer.id whenever the
    call is ownership-gated (approve, request-revision, authorize-scrap,
    select-exchange, cancel as customer)."""
    return build_user_headers(user_id, "Customer")


def make_inspector_headers(user_id: str) -> dict:
    """For QualityInspector (opaque). Use a custom operator id when a test
    needs a specific inspector identity (e.g. the segregation-of-duties rule
    compares the inspector's X-User-ID to the assigned technician id)."""
    return build_user_headers(user_id, "QualityInspector")
