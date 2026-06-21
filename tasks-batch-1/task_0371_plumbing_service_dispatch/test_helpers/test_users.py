"""Pre-built role headers for every role in the PRD (§2.1).

Two opaque roles (OfficeManager, Dispatcher) carry an audit-only X-User-ID that
is never compared to any entity id, so a shared constant is the canonical form.

Two entity_backed roles (Technician -> Technician.id, Customer -> Customer.id)
have ownership checks that compare X-User-ID to a real entity id. For those,
ownership-gated calls MUST use the per-instance builder threading the actual
entity id; the shared constants are only safe for non-ownership scenarios
(e.g. 403/404 checks where the caller does not own the subject resource).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operators — shared constant is canonical.
    "office_manager_headers": build_user_headers("test-office-manager-1", "OfficeManager"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # entity_backed roles — shared constant is a fallback for non-ownership tests only.
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    whenever the call is ownership-gated (depart/arrive/start/complete/estimate ops)."""
    return build_user_headers(user_id, "Technician")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id whenever
    the call is ownership-gated (approve/decline/file callback on own jobs)."""
    return build_user_headers(user_id, "Customer")


def make_office_manager_headers(user_id: str = "test-office-manager-1") -> dict:
    """OfficeManager is opaque; the id is audit-only."""
    return build_user_headers(user_id, "OfficeManager")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; the id is audit-only."""
    return build_user_headers(user_id, "Dispatcher")
