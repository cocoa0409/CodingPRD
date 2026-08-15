"""Pre-built role headers for every role in the PRD (§2.1).

PRD §2.1: when X-User-Role is Customer, X-User-ID is the id of the acting
Customer record — the ownership check compares it to the resource's
customer-reference field. All other five roles are opaque operator
identifiers never compared to any entity's id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles.
TEST_USERS = {
    "shop_manager_headers": build_user_headers("mgr-1", "ShopManager"),
    "csr_headers": build_user_headers("csr-1", "CustomerServiceRep"),
    "technician_headers": build_user_headers("tech-1", "Technician"),
    "inspector_headers": build_user_headers("insp-9", "Inspector"),
    "parts_buyer_headers": build_user_headers("buyer-1", "PartsBuyer"),
    # Customer is entity-backed — shared constant only for non-ownership probes.
    "customer_headers": build_user_headers("customer-opaque-1", "Customer"),
}

SHOP_MANAGER = TEST_USERS["shop_manager_headers"]
CSR = TEST_USERS["csr_headers"]
TECHNICIAN = TEST_USERS["technician_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
PARTS_BUYER = TEST_USERS["parts_buyer_headers"]

# Distinct opaque users for segregation-of-duties probes.
TECHNICIAN_ALT = build_user_headers("tech-2", "Technician")
INSPECTOR_ALT = build_user_headers("insp-10", "Inspector")

# Headers with neither X-User-ID nor X-User-Role — for the priority-1
# authentication check.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the Customer role. PRD §2.1: X-User-ID MUST be the
    Customer record's id for ownership-gated calls (quote approval/decline,
    PMA approval, warranty claim, invoice pay)."""
    return build_user_headers(customer_id, "Customer")


def make_technician_headers(user_id: str) -> dict:
    """Headers for a Technician with a specific opaque user id (used to pin
    technician_user_id on a work order)."""
    return build_user_headers(user_id, "Technician")


def make_inspector_headers(user_id: str) -> dict:
    """Headers for an Inspector with a specific opaque user id (used to
    exercise the segregation-of-duties rule against technician_user_id)."""
    return build_user_headers(user_id, "Inspector")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder used by role-matrix probes."""
    return build_user_headers(user_id, role)
