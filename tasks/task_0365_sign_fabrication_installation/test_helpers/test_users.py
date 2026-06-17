"""Pre-built role headers for every role in the PRD (§2.1).

The system recognizes exactly five roles, all carrying an OPAQUE identity:
ShopManager, Designer, Customer, Surveyor, PermitClerk. Per PRD §2.1, X-User-ID
is never compared against any entity's id (there are no per-user ownership
checks); authorization is determined entirely by X-User-Role. The shared-constant
headers below are therefore sufficient for every test, and no per-instance
entity_backed builder is needed.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "surveyor_headers": build_user_headers("test-surveyor-1", "Surveyor"),
    "permit_clerk_headers": build_user_headers("test-permit-clerk-1", "PermitClerk"),
}


def make_shop_manager_headers(user_id: str = "test-shop-manager-1") -> dict:
    return build_user_headers(user_id, "ShopManager")


def make_designer_headers(user_id: str = "test-designer-1") -> dict:
    return build_user_headers(user_id, "Designer")


def make_customer_headers(user_id: str = "test-customer-1") -> dict:
    return build_user_headers(user_id, "Customer")


def make_surveyor_headers(user_id: str = "test-surveyor-1") -> dict:
    return build_user_headers(user_id, "Surveyor")


def make_permit_clerk_headers(user_id: str = "test-permit-clerk-1") -> dict:
    return build_user_headers(user_id, "PermitClerk")
