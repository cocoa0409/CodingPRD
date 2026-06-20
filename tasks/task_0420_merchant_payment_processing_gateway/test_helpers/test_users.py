"""Pre-built role headers for every role in the PRD.

Roles (spelled exactly): MerchantUser, UnderwritingOfficer, PlatformOperator, Anonymous.

A MerchantUser is entity-backed by a Merchant: X-User-ID is the acting Merchant's id.
Ownership-gated calls MUST use make_merchant_user_headers(merchant_id). The shared
TEST_USERS entry is only a fallback for tests that don't exercise ownership (e.g. a
403/401 denial test or a 404-on-missing-resource test).

UnderwritingOfficer and PlatformOperator are opaque operator identities: X-User-ID is
an arbitrary operator id not tied to any persisted entity, so the shared constant is the
canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Merchant -> shared constant is a non-ownership fallback only.
    "merchant_user_headers": build_user_headers("test-merchant-user-1", "MerchantUser"),
    # opaque operator roles -> shared constant is canonical.
    "underwriting_officer_headers": build_user_headers("test-underwriter-1", "UnderwritingOfficer"),
    "platform_operator_headers": build_user_headers("test-operator-1", "PlatformOperator"),
}


def make_merchant_user_headers(merchant_id: str) -> dict:
    """For MerchantUser (entity_backed:Merchant). Pass the actual Merchant.id as the
    acting principal whenever the call is ownership-gated."""
    return build_user_headers(merchant_id, "MerchantUser")


def make_underwriting_officer_headers(user_id: str = "test-underwriter-1") -> dict:
    return build_user_headers(user_id, "UnderwritingOfficer")


def make_platform_operator_headers(user_id: str = "test-operator-1") -> dict:
    return build_user_headers(user_id, "PlatformOperator")
