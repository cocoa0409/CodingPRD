"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (PlatformAdmin, PhysicianUser,
# PayerReviewer whose X-User-ID is never compared to an entity id), and for
# tests that do not exercise SupplierUser ownership (e.g. 401/403/404 paths).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "physician_headers": build_user_headers("physician-1", "PhysicianUser"),
    "payer_headers": build_user_headers("payer-1", "PayerReviewer"),
    # Fallback only — for SupplierUser calls that are NOT ownership-gated.
    "supplier_headers": build_user_headers("supplier-fallback-1", "SupplierUser"),
}


# Per-instance builder — REQUIRED for SupplierUser (identity entity_backed:Supplier).
# Pass the actual Supplier.id as user_id for any ownership-gated supplier call.
def make_supplier_headers(supplier_id: str) -> dict:
    """For SupplierUser (entity_backed:Supplier). Pass the actual Supplier.id
    so ownership checks comparing the order's supplier_id to X-User-ID pass."""
    return build_user_headers(supplier_id, "SupplierUser")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_physician_headers(user_id: str = "physician-1") -> dict:
    return build_user_headers(user_id, "PhysicianUser")


def make_payer_headers(user_id: str = "payer-1") -> dict:
    return build_user_headers(user_id, "PayerReviewer")
