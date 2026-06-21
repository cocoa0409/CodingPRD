"""Pre-built role headers for every role in the PRD.

Roles (PRD §2.1): Anonymous, Customer, StorePicker, StoreAssociate, StoreManager,
PlatformAdmin. Only Customer is entity_backed — its X-User-ID must equal the acting
Customer's id whenever the call is ownership-gated (orders/substitutions). All other
roles are opaque: X-User-ID is an arbitrary operator identifier never compared to any
entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constant is the canonical form.
    "picker_headers": build_user_headers("test-picker-1", "StorePicker"),
    "associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    "manager_headers": build_user_headers("test-manager-1", "StoreManager"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


# Per-instance builder — REQUIRED for the entity_backed Customer role. Pass the actual
# Customer.id as user_id whenever the downstream call is ownership-gated (orders,
# order lines, submit, substitution accept/decline, curbside check-in).
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id."""
    return build_user_headers(user_id, "Customer")


def make_picker_headers(user_id: str = "test-picker-1") -> dict:
    return build_user_headers(user_id, "StorePicker")


def make_associate_headers(user_id: str = "test-associate-1") -> dict:
    return build_user_headers(user_id, "StoreAssociate")


def make_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "StoreManager")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


# Anonymous caller — used only for customer self-registration. Per PRD §2.1 the
# clock and self-registration endpoints are exempt from authentication, so this
# carries no auth headers.
def anonymous_headers() -> dict:
    return {}
