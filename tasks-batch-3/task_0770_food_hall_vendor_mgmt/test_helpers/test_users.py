"""Pre-built role headers for every role in the PRD (§2.1).

HallManager, HealthInspector, and POSOperator carry opaque X-User-ID values that
the server never compares to a persisted entity. Vendor is entity_backed: when a
call is ownership-gated (accept / fulfill / reject an order on its own stall, or
dispute a settlement on its own lease), the header's X-User-ID MUST be the actual
Vendor.id — use make_vendor_headers(vendor_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests whose success does NOT
# depend on the caller owning the subject resource (401/403/404/422 checks).
TEST_USERS = {
    "hall_manager_headers": build_user_headers("hall-manager-1", "HallManager"),
    "health_inspector_headers": build_user_headers("health-inspector-1", "HealthInspector"),
    "pos_operator_headers": build_user_headers("pos-operator-1", "POSOperator"),
    # entity_backed fallback — only for non-ownership tests:
    "vendor_headers": build_user_headers("vendor-1", "Vendor"),
}

# No auth headers at all (PRD §2.1 — a call with missing headers fails
# ERR_UNAUTHENTICATED).
ANONYMOUS_HEADERS: dict = {}


# Per-instance builders.
def make_hall_manager_headers(user_id: str = "hall-manager-1") -> dict:
    """HallManager is opaque; user_id is recorded but not compared to any entity."""
    return build_user_headers(user_id, "HallManager")


def make_health_inspector_headers(user_id: str = "health-inspector-1") -> dict:
    """HealthInspector is opaque; user_id is recorded but not compared to any entity."""
    return build_user_headers(user_id, "HealthInspector")


def make_pos_operator_headers(user_id: str = "pos-operator-1") -> dict:
    """POSOperator is opaque; user_id is recorded but not compared to any entity."""
    return build_user_headers(user_id, "POSOperator")


def make_vendor_headers(vendor_id: str) -> dict:
    """For Vendor (entity_backed:Vendor). Pass the actual Vendor.id as user_id on
    every ownership-gated order or settlement call so X-User-ID equals the stall's
    current_vendor_id / the settlement's lease vendor_id."""
    return build_user_headers(vendor_id, "Vendor")
