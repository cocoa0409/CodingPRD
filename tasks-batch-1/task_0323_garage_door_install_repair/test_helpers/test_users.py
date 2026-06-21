"""Pre-built role headers for every role in the PRD (§2.1).

Four roles, spelled exactly: Customer, Dispatcher, Technician, ServiceManager.

- Customer and Technician are entity-backed: X-User-ID must be the acting
  entity's own id for ownership / on-site checks to pass. Use the per-instance
  builders below with the real entity id.
- Dispatcher and ServiceManager carry an opaque operator id not tied to any
  entity (§2.1); the shared constants are the canonical form. The exception is
  the invoice segregation check (§3.8), which compares the manager's X-User-ID
  to the job's completed_by_user_id — build that header with make_service_manager_headers.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles and for tests that do not exercise
# entity ownership.
TEST_USERS = {
    # opaque operator roles
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "service_manager_headers": build_user_headers("manager-1", "ServiceManager"),
    # entity-backed fallbacks (non-ownership tests only)
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
}


# Per-instance builders.
def make_customer_headers(user_id: str) -> dict:
    """Customer (entity_backed:Customer). Pass the actual Customer.id so that
    ownership checks on accept/decline and own-resource reads pass (§2.1)."""
    return build_user_headers(user_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """Technician (entity_backed:Technician). Pass the actual Technician.id so
    on-site transition checks (technician_id == X-User-ID) pass (§2.1)."""
    return build_user_headers(user_id, "Technician")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    """Dispatcher (opaque). The id is not matched against any entity (§2.1)."""
    return build_user_headers(user_id, "Dispatcher")


def make_service_manager_headers(user_id: str = "manager-1") -> dict:
    """ServiceManager (opaque). The id is only compared in the invoice
    segregation-of-duties check (§3.8); pass a distinct value to drive that
    check one way or the other."""
    return build_user_headers(user_id, "ServiceManager")
