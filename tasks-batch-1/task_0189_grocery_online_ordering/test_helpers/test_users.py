"""Pre-built role headers for every role in the PRD.

PlatformAdmin and StoreOps carry identity: opaque — X-User-ID is an opaque operator
identifier the server never compares to any entity id, so a shared constant is
canonical for these roles.

Customer and Picker are entity_backed roles. Ownership/eligibility checks compare
X-User-ID to an entity id (the Customer.id for a customer, a Picker.id of the
order's store for a picker). For ownership-gated calls, fixtures MUST call
make_customer_headers(customer_id) / make_picker_headers(picker_id) with the actual
entity id rather than the shared constant. The shared constant is a fallback for
non-ownership-gated tests only.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership-gated tests.
TEST_USERS = {
    # opaque roles: shared constants are canonical.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "store_ops_headers": build_user_headers("test-store-ops-1", "StoreOps"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "picker_headers": build_user_headers("test-picker-1", "Picker"),
    # Anonymous (explicit no-auth calls).
    "anonymous_headers": {},
}


def make_platform_admin_headers(opaque_id: str = "test-platform-admin-1") -> dict:
    """For PlatformAdmin role (identity: opaque). X-User-ID is opaque."""
    return build_user_headers(opaque_id, "PlatformAdmin")


def make_store_ops_headers(opaque_id: str = "test-store-ops-1") -> dict:
    """For StoreOps role (identity: opaque). X-User-ID is opaque."""
    return build_user_headers(opaque_id, "StoreOps")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer role (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (place/edit/cancel/decide on own
    orders)."""
    return build_user_headers(customer_id, "Customer")


def make_picker_headers(picker_id: str) -> dict:
    """For Picker role (entity_backed:Picker). Pass the actual Picker.id as user_id
    whenever the call is ownership/eligibility-gated (claim/pick/stage/propose)."""
    return build_user_headers(picker_id, "Picker")
