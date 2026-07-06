"""Pre-built role headers for every role in the PRD.

Per §2.1 the system recognizes exactly three roles: Customer, Clerk, Manager.
- Clerk and Manager carry an opaque X-User-ID the server never compares to any
  entity id; their shared constants are the canonical form.
- Customer is entity-backed: X-User-ID must equal the acting Customer entity's
  id, and ownership checks on any resource referencing a customer (customer_id
  or consignor_id) compare that FK to X-User-ID. For owner-gated Customer calls
  a builder is provided to mint headers whose id matches the target customer.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (Clerk/Manager) and for Customer only
# in non-ownership tests (400/404/role-denial style).
TEST_USERS = {
    "clerk_headers": build_user_headers("clerk-1", "Clerk"),
    "manager_headers": build_user_headers("manager-1", "Manager"),
    # Opaque fallback Customer constant — used only for non-ownership tests.
    "customer_headers": build_user_headers("customer-1", "Customer"),
}


# Per-instance builders.
def make_clerk_headers(user_id: str = "clerk-1") -> dict:
    """Clerk (opaque identity)."""
    return build_user_headers(user_id, "Clerk")


def make_manager_headers(user_id: str = "manager-1") -> dict:
    """Manager (opaque identity)."""
    return build_user_headers(user_id, "Manager")


def make_customer_headers(customer_id: str) -> dict:
    """Customer (entity_backed:Customer). Pass the actual Customer.id as
    customer_id whenever the call is ownership-gated (acting on own
    subscription, reservation, pre-order, registration, consignment, or
    grading submission)."""
    return build_user_headers(customer_id, "Customer")
