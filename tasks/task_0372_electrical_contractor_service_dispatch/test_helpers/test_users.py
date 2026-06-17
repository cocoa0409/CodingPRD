"""Pre-built role headers for every role in the PRD (§2.1).

Roles:
  - Dispatcher  : opaque identity (X-User-ID is an opaque operator id)
  - Inspector   : opaque identity
  - Customer    : entity_backed — X-User-ID must be a real Customer.id for ownership
  - Technician  : entity_backed — X-User-ID must be a real Technician.id for ownership

Ownership-gated calls (a Customer acting on its own job, a Technician acting on its
own dispatch/truck) MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership
# (e.g. 401/403/404/422 paths, or any Dispatcher/Inspector operation).
TEST_USERS = {
    "dispatcher_headers": build_user_headers("dispatcher-op-1", "Dispatcher"),
    "inspector_headers": build_user_headers("inspector-op-1", "Inspector"),
    # entity_backed shared constants — NOT tied to a real entity; use only on
    # non-ownership tests (these intentionally never match any real entity id).
    "customer_headers": build_user_headers("customer-not-real-1", "Customer"),
    "technician_headers": build_user_headers("technician-not-real-1", "Technician"),
}


# ─── Per-instance builders (mandatory for entity_backed roles) ────────────
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the real Customer.id whenever
    the call is ownership-gated (accept/reject/cancel/file-callback on own job)."""
    return build_user_headers(user_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the real Technician.id whenever
    the call is ownership-gated (depart/arrive/complete/record-material on own work)."""
    return build_user_headers(user_id, "Technician")


def make_dispatcher_headers(user_id: str = "dispatcher-op-1") -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_inspector_headers(user_id: str = "inspector-op-1") -> dict:
    return build_user_headers(user_id, "Inspector")
