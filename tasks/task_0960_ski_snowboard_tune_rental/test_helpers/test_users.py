"""Pre-built role headers for every role in the PRD (User and Role-Based Access Control)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (FrontDesk / Technician / Manager carry an
# opaque operator identifier never compared to any entity id), and for Customer-role
# calls whose success does not depend on owning the subject resource.
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity-backed by the Customer record). Pass the actual
    Customer.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")


def make_front_desk_headers(user_id: str = "test-front-desk-1") -> dict:
    return build_user_headers(user_id, "FrontDesk")


def make_technician_headers(user_id: str = "test-technician-1") -> dict:
    return build_user_headers(user_id, "Technician")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "Manager")
