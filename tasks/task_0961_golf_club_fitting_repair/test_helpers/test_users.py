"""Pre-built role headers for every role in the PRD (§2.1).

Customer and staff roles are entity-backed: whenever a call is ownership- or
attribution-gated, build headers from the real entity id via the make_*
builders below. The shared TEST_USERS constants are only safe for the opaque
ShopAdmin role and for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — ShopAdmin is the only opaque role; the staff/customer
# entries are fallbacks for non-ownership tests only.
TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-shop-admin-1", "ShopAdmin"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "fitting_specialist_headers": build_user_headers("test-specialist-1", "FittingSpecialist"),
    "repair_technician_headers": build_user_headers("test-technician-1", "RepairTechnician"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "shop_manager_headers": build_user_headers("test-manager-1", "ShopManager"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity_backed:Customer — pass the real Customer.id."""
    return build_user_headers(user_id, "Customer")


def make_fitting_specialist_headers(user_id: str) -> dict:
    """FittingSpecialist is entity_backed:StaffMember — pass the real StaffMember.id."""
    return build_user_headers(user_id, "FittingSpecialist")


def make_repair_technician_headers(user_id: str) -> dict:
    """RepairTechnician is entity_backed:StaffMember — pass the real StaffMember.id."""
    return build_user_headers(user_id, "RepairTechnician")


def make_instructor_headers(user_id: str) -> dict:
    """Instructor is entity_backed:StaffMember — pass the real StaffMember.id."""
    return build_user_headers(user_id, "Instructor")


def make_shop_manager_headers(user_id: str) -> dict:
    """ShopManager is entity_backed:StaffMember — pass the real StaffMember.id."""
    return build_user_headers(user_id, "ShopManager")


def make_shop_admin_headers(user_id: str = "test-shop-admin-1") -> dict:
    """ShopAdmin is opaque; any identifier works."""
    return build_user_headers(user_id, "ShopAdmin")
