"""Pre-built role headers for every role in the BNPL PRD §2.1.

Servicer is an opaque operational identity (X-User-ID is not tied to any entity),
so its shared constant is the canonical form. Borrower and Merchant are
entity-backed: ownership checks compare X-User-ID against the resource's
borrower/merchant foreign key, so tests that exercise ownership MUST use the
per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — Servicer is opaque (canonical). The Borrower/Merchant
# shared constants are fallbacks usable ONLY for tests that do not exercise
# ownership (401/403/404/422 on a resource the actor never legitimately owns).
TEST_USERS = {
    "servicer_headers": build_user_headers("servicer-operator-1", "Servicer"),
    "borrower_headers": build_user_headers("test-borrower-1", "Borrower"),
    "merchant_headers": build_user_headers("test-merchant-1", "Merchant"),
}


def make_servicer_headers(user_id: str = "servicer-operator-1") -> dict:
    """Servicer is opaque; any operator id is accepted (PRD §2.1)."""
    return build_user_headers(user_id, "Servicer")


def make_borrower_headers(user_id: str) -> dict:
    """For the Borrower role (entity_backed:Borrower). Pass the actual Borrower.id
    as user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Borrower")


def make_merchant_headers(user_id: str) -> dict:
    """For the Merchant role (entity_backed:Merchant). Pass the actual Merchant.id
    as user_id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(user_id, "Merchant")
