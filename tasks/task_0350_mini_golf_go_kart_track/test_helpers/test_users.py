"""Pre-built role headers for every role in the PRD.

The PRD recognises exactly three roles: OpsManager, Cashier, Guest.

- OpsManager and Cashier carry an OPAQUE X-User-ID never compared to any
  entity id, so the shared constant form is canonical for them.
- Guest is entity_backed:Guest — X-User-ID must equal the acting Guest.id.
  Ownership-gated calls MUST use make_guest_headers(guest_id) with the real
  Guest id; the shared constant is only a fallback for non-ownership tests
  (e.g. self-registration POST /guests, or 401/403 negative checks).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "ops_manager_headers": build_user_headers("ops-1", "OpsManager"),
    "cashier_headers": build_user_headers("cash-1", "Cashier"),
    # Guest is entity_backed — this constant is a fallback for self-register /
    # negative tests only; ownership-gated calls must thread the real Guest id.
    "guest_headers": build_user_headers("guest-1", "Guest"),
}


def make_ops_manager_headers(user_id: str = "ops-1") -> dict:
    """Headers for OpsManager (opaque identity)."""
    return build_user_headers(user_id, "OpsManager")


def make_cashier_headers(user_id: str = "cash-1") -> dict:
    """Headers for Cashier (opaque identity)."""
    return build_user_headers(user_id, "Cashier")


def make_guest_headers(user_id: str) -> dict:
    """Headers for Guest (entity_backed:Guest). Pass the actual Guest.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Guest")
