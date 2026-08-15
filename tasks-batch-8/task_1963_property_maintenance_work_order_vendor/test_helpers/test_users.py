"""Pre-built role headers for every role in the PRD.

Resident, Technician and Vendor are entity-backed roles: their X-User-ID must
equal the id of the entity they act as. Use the per-instance builders with the
actual entity id for any ownership-gated call. The shared constants are safe
only for opaque roles (Dispatcher, PropertyManager) and for tests that never
exercise an ownership check.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "manager_headers": build_user_headers("test-manager-1", "PropertyManager"),
    # Entity-backed roles — fallback only for tests that do not exercise ownership.
    "resident_headers": build_user_headers("test-resident-1", "Resident"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
}


def make_resident_headers(user_id: str) -> dict:
    """Resident is entity-backed: pass the actual Resident.id as user_id
    whenever the call is ownership-gated (create/sign-off/reopen/cancel,
    chargeback DISPUTE/PAY)."""
    return build_user_headers(user_id, "Resident")


def make_technician_headers(user_id: str) -> dict:
    """Technician is entity-backed: pass the actual Technician.id as user_id
    whenever the call is ownership-gated (start/complete/parts/purchase-requests)."""
    return build_user_headers(user_id, "Technician")


def make_vendor_headers(user_id: str) -> dict:
    """Vendor is entity-backed: pass the actual Vendor.id as user_id
    whenever the call is ownership-gated (start/complete/parts/purchase-requests)."""
    return build_user_headers(user_id, "Vendor")


def make_dispatcher_headers(user_id: str = "test-dispatcher-1") -> dict:
    """Dispatcher is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "Dispatcher")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    """PropertyManager is opaque; user_id is not compared to any entity id."""
    return build_user_headers(user_id, "PropertyManager")
