"""Pre-built role headers for every role in the PRD.

MerchantAdmin and PlatformOperator are opaque identities — X-User-ID is not tied
to any persisted entity, so a shared constant is the canonical form.

Shopper is entity_backed:Customer — X-User-ID must equal the acting Customer's id
for ownership checks to pass. Use make_shopper_headers(customer_id) whenever the
call is ownership-gated (any /carts operation owned by that customer).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "merchant_admin_headers": build_user_headers("test-merchant-admin-1", "MerchantAdmin"),
    "platform_operator_headers": build_user_headers("test-platform-operator-1", "PlatformOperator"),
    # entity_backed:Customer — shared constant is a fallback for non-ownership tests only
    # (e.g. 400-on-bad-payload, 403-forbidden-role before any ownership compare).
    "shopper_headers": build_user_headers("test-shopper-1", "Shopper"),
}


def make_shopper_headers(customer_id: str) -> dict:
    """For Shopper (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Shopper")


def make_merchant_admin_headers(user_id: str = "test-merchant-admin-1") -> dict:
    return build_user_headers(user_id, "MerchantAdmin")


def make_platform_operator_headers(user_id: str = "test-platform-operator-1") -> dict:
    return build_user_headers(user_id, "PlatformOperator")
