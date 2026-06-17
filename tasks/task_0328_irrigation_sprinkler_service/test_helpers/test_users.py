"""Pre-built role headers for every role in the PRD (PRD §2.1).

Roles:
  Dispatcher      -> opaque identity (X-User-ID not compared to any entity)
  Technician      -> entity_backed:Technician (X-User-ID == acting Technician.id)
  Customer        -> entity_backed:Customer   (X-User-ID == acting Customer.id)
  BackflowTester  -> entity_backed:Technician (X-User-ID == acting Technician.id)
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque Dispatcher, and for non-ownership negative tests.
TEST_USERS = {
    # Dispatcher is opaque: shared constant is the canonical form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only
    # (e.g. forbidden-role / not-found cases where ownership is never reached).
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "backflow_tester_headers": build_user_headers("test-tester-1", "BackflowTester"),
}


# Per-instance builders — required for every entity_backed role.
def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; user_id is recorded but not ownership-compared."""
    return build_user_headers(user_id, "Dispatcher")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id
    whenever the call is ownership-gated (depart/arrive/complete/fail)."""
    return build_user_headers(user_id, "Technician")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id whenever
    the call is ownership-gated (quote approve/reject/request-changes)."""
    return build_user_headers(user_id, "Customer")


def make_backflow_tester_headers(user_id: str) -> dict:
    """For BackflowTester (entity_backed:Technician). Pass the acting Technician.id."""
    return build_user_headers(user_id, "BackflowTester")
