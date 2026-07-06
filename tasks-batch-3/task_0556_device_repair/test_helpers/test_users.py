"""Pre-built role headers for every role in the PRD.

Two identity-backed roles (Customer, Technician) require per-instance builders
so ownership / identity checks compare X-User-ID against a real entity id.
The two opaque operational roles (ServiceAdvisor, StoreManager) use shared
constants.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#  - ServiceAdvisor / StoreManager are opaque: the shared constant is canonical.
#  - Customer / Technician entries are fallbacks for non-ownership tests only
#    (e.g. 400 missing-context, 404 not-found, or role-permission checks).
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "service_advisor_headers": build_user_headers("test-advisor-1", "ServiceAdvisor"),
    "store_manager_headers": build_user_headers("test-manager-1", "StoreManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id so
    ownership checks (RepairTicket.customer_id / TradeIn.customer_id == X-User-ID)
    succeed."""
    return build_user_headers(user_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """For Technician (entity_backed:Technician). Pass the actual Technician.id;
    X-User-ID identifies a persisted technician for bench actions."""
    return build_user_headers(user_id, "Technician")


def make_service_advisor_headers(user_id: str = "test-advisor-1") -> dict:
    """For ServiceAdvisor (opaque)."""
    return build_user_headers(user_id, "ServiceAdvisor")


def make_store_manager_headers(user_id: str = "test-manager-1") -> dict:
    """For StoreManager (opaque)."""
    return build_user_headers(user_id, "StoreManager")
