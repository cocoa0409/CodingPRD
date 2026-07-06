"""Pre-built role headers for every role in the PRD.

- Manager identity is opaque: a shared constant is the canonical form; a Manager
  is never ownership-restricted and can perform every Barista/Customer operation.
- Barista identity is the acting Barista.id; Customer identity is the acting
  Member.id. For those entity-backed roles, ownership-gated calls MUST use the
  per-instance builders with the real entity id, or the acting identity will not
  resolve (ERR_ROSTER_MISMATCH) / will fail the ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Manager: opaque operator identifier, superset capability.
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    # Shared fallbacks for non-ownership scenarios only.
    "barista_headers": build_user_headers("test-barista-1", "Barista"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """Manager headers (opaque id)."""
    return build_user_headers(user_id, "Manager")


def make_barista_headers(user_id: str) -> dict:
    """For Barista (identity = Barista.id). Pass the real Barista.id."""
    return build_user_headers(user_id, "Barista")


def make_customer_headers(user_id: str) -> dict:
    """For Customer (identity = Member.id). Pass the real Member.id whenever the
    call is ownership-gated."""
    return build_user_headers(user_id, "Customer")
