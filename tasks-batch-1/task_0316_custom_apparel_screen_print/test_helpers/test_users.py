"""Pre-built role headers for every role in the PRD (§2.1).

ShopManager, ArtStaff, and System carry opaque X-User-IDs the server never resolves
to a stored entity, so shared constants are their canonical form. Customer is
entity_backed: its X-User-ID must equal the acting Customer entity's id for ownership
checks to pass, so the per-instance builder make_customer_headers(customer_id) is
mandatory for any ownership-gated call.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "art_staff_headers": build_user_headers("test-art-staff-1", "ArtStaff"),
    # Customer shared constant — only safe for non-ownership tests (e.g. 400/404/403
    # role-denial paths). Ownership-gated calls MUST use make_customer_headers().
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated (approve, request-changes, pay, cancel-own)."""
    return build_user_headers(user_id, "Customer")
