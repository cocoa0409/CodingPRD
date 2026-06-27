"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. The first four roles are opaque (X-User-ID is an opaque
# operator id never compared to any entity), so their shared constant is the
# canonical form. The Customer role is entity_backed: its shared constant is a
# fallback for non-ownership tests only; ownership-gated calls MUST use
# make_customer_headers(customer_id).
TEST_USERS = {
    "inventory_manager_headers": build_user_headers("test-invmgr-1", "InventoryManager"),
    "livestock_keeper_headers": build_user_headers("test-keeper-1", "LivestockKeeper"),
    "clinic_vet_headers": build_user_headers("test-vet-1", "ClinicVet"),
    "store_clerk_headers": build_user_headers("test-clerk-1", "StoreClerk"),
    # entity_backed Customer: fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual
    Customer.id as user_id for any ownership-gated call (subscription
    pause/resume/cancel, special-order cancel, creating own subscription/order)."""
    return build_user_headers(user_id, "Customer")


def make_inventory_manager_headers() -> dict:
    return build_user_headers("test-invmgr-1", "InventoryManager")


def make_livestock_keeper_headers() -> dict:
    return build_user_headers("test-keeper-1", "LivestockKeeper")


def make_clinic_vet_headers() -> dict:
    return build_user_headers("test-vet-1", "ClinicVet")


def make_store_clerk_headers() -> dict:
    return build_user_headers("test-clerk-1", "StoreClerk")
