"""Pre-built role headers for every role in the Sales Tax Nexus PRD.

PlatformAdmin, TaxPreparer, TaxApprover, and Auditor are opaque roles whose
X-User-ID is never compared to a persisted entity, so a shared constant is the
canonical form. Seller is entity-backed: ownership checks compare a resource's
seller_id to X-User-ID, so any ownership-gated Seller call MUST use
make_seller_headers(seller["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Opaque roles: canonical form.
#  - Seller: a fallback usable only by tests that do NOT exercise ownership
#    (e.g. a 401/403/404 check before ownership matters); ownership-gated Seller
#    calls must use make_seller_headers() instead.
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "seller_headers": build_user_headers("seller-unowned", "Seller"),
    "preparer_headers": build_user_headers("preparer-1", "TaxPreparer"),
    "preparer_alt_headers": build_user_headers("preparer-2", "TaxPreparer"),
    "approver_headers": build_user_headers("approver-1", "TaxApprover"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
}


def make_seller_headers(seller_id: str) -> dict:
    """For the Seller role (entity_backed:Seller). Pass the actual Seller.id as
    X-User-ID whenever the call is ownership-gated."""
    return build_user_headers(seller_id, "Seller")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_preparer_headers(user_id: str = "preparer-1") -> dict:
    return build_user_headers(user_id, "TaxPreparer")


def make_approver_headers(user_id: str = "approver-1") -> dict:
    return build_user_headers(user_id, "TaxApprover")


def make_auditor_headers(user_id: str = "aud-1") -> dict:
    return build_user_headers(user_id, "Auditor")
