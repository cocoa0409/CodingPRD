"""Pre-built role headers for every role in the PRD.

Four of the five roles are opaque operator identities (ShopAdmin, ShopManager,
Designer, Installer) — the server logs X-User-ID but never compares it to any
entity id, so the shared-constant form is canonical for them. The Customer role
is entity-backed: X-User-ID must equal the acting Customer entity's id, so any
ownership-gated customer call (contract, draw pay, change-order approve / reject /
request-revision) MUST use make_customer_headers(customer_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the four opaque roles, and for Customer-role tests
# whose success does NOT depend on owning the subject resource (e.g. a 403
# not-owner test that deliberately supplies the wrong customer id).
TEST_USERS = {
    "shop_admin_headers": build_user_headers("test-admin-1", "ShopAdmin"),
    "shop_manager_headers": build_user_headers("test-manager-1", "ShopManager"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "installer_headers": build_user_headers("test-installer-1", "Installer"),
    # Fallback Customer constant — only for non-ownership Customer tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For the Customer role (entity_backed:Customer). Pass the actual Customer.id
    as user_id whenever the call is ownership-gated (contracting a project, paying
    a draw, approving/rejecting/requesting-revision on a change order)."""
    return build_user_headers(customer_id, "Customer")


def make_unknown_role_headers(user_id: str = "test-unknown-1", role: str = "Wizard") -> dict:
    """Headers whose X-User-Role is NOT one of the five recognized roles
    (ShopAdmin, ShopManager, Designer, Customer, Installer). Used to exercise the
    ERR_MISSING_OR_INVALID_USER_CONTEXT path for an unknown role."""
    return build_user_headers(user_id, role)
