"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ShopAdmin, ServiceManager, Technician, WindingTechnician,
Estimator) carry an operator identifier that is never compared to an entity
id, so shared constants are safe. The Customer role is entity-backed:
ownership-gated calls MUST use make_customer_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque roles. The technician/winding constants use
# the canonical operator ids "op-t" / "op-w" so segregation-of-duties pairs
# are distinct by default; use the make_* builders when a test needs a
# specific operator identity.
TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-admin-1", "ShopAdmin"),
    "service_manager_headers": build_user_headers("test-mgr-1", "ServiceManager"),
    "estimator_headers": build_user_headers("test-est-1", "Estimator"),
    "technician_headers": build_user_headers("op-t", "Technician"),
    "winding_technician_headers": build_user_headers("op-w", "WindingTechnician"),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only. Ownership-gated calls must use make_customer_headers().
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_shop_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShopAdmin")


def make_service_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceManager")


def make_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Estimator")


def make_technician_headers(user_id: str) -> dict:
    """Technician is an opaque role; user_id selects the operator identity
    recorded as recorded_by on test records (PRD §2.1)."""
    return build_user_headers(user_id, "Technician")


def make_winding_technician_headers(user_id: str) -> dict:
    """WindingTechnician is an opaque role; user_id selects the operator
    identity recorded as recorded_by on coil data records (PRD §2.1)."""
    return build_user_headers(user_id, "WindingTechnician")


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity-backed: pass the acting Customer.id as user_id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Customer")
