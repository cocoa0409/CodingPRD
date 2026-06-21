"""Pre-built role headers for every role in the PRD.

Two roles are opaque (FrontDeskClerk, ShopManager): their X-User-ID is not tied
to any persisted entity, so the shared constant is the canonical form.

Two roles are entity-backed (RepairTechnician -> Technician.id,
Customer -> Customer.id): for ownership/authorship-gated calls, headers MUST be
built per-instance with the actual entity id via make_technician_headers() /
make_customer_headers(). The shared constants are fallbacks for non-ownership
tests only (e.g. a 403 forbidden-role probe).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "front_desk_headers": build_user_headers("clerk-1", "FrontDeskClerk"),
    "shop_manager_headers": build_user_headers("manager-1", "ShopManager"),
    # Entity-backed roles — shared constant is a NON-ownership fallback only.
    "technician_headers": build_user_headers("technician-1", "RepairTechnician"),
    "customer_headers": build_user_headers("customer-1", "Customer"),
}


def make_front_desk_headers(user_id: str = "clerk-1") -> dict:
    """FrontDeskClerk (opaque). user_id is recorded but never compared."""
    return build_user_headers(user_id, "FrontDeskClerk")


def make_shop_manager_headers(user_id: str = "manager-1") -> dict:
    """ShopManager (opaque). user_id is recorded but never compared."""
    return build_user_headers(user_id, "ShopManager")


def make_technician_headers(user_id: str) -> dict:
    """RepairTechnician (entity_backed:Technician). Pass the actual Technician.id
    whenever the call is authorship/ownership-gated (e.g. estimate authoring,
    service-line and parts management)."""
    return build_user_headers(user_id, "RepairTechnician")


def make_customer_headers(user_id: str) -> dict:
    """Customer (entity_backed:Customer). Pass the actual Customer.id whenever the
    call is ownership-gated (approve/reject estimate, file warranty claim)."""
    return build_user_headers(user_id, "Customer")
