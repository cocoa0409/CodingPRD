"""Pre-built role headers for every role in the PRD.

The PRD recognizes exactly five roles. DispatchAdmin and Dispatcher are opaque
operator identities (X-User-ID is never compared to any entity id). CorporateBooker,
AffiliatePartner, and Chauffeur are entity-backed: X-User-ID must equal the id of
the acting CorporateAccount / Affiliate / Chauffeur for ownership-gated calls.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for the opaque operator roles, and for tests that do
# NOT exercise ownership (e.g. 404 / 400 / 422 / forbidden checks).
TEST_USERS = {
    "dispatch_admin_headers": build_user_headers("test-admin-1", "DispatchAdmin"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    # Entity-backed fallbacks — only valid for non-ownership tests.
    "corporate_booker_headers": build_user_headers("test-booker-1", "CorporateBooker"),
    "affiliate_partner_headers": build_user_headers("test-affiliate-1", "AffiliatePartner"),
    "chauffeur_headers": build_user_headers("test-chauffeur-1", "Chauffeur"),
}


# Per-instance builders — required for every entity-backed role. Pass the actual
# entity id whenever the downstream call is ownership-gated.
def make_corporate_booker_headers(account_id: str) -> dict:
    """For CorporateBooker (entity_backed:CorporateAccount). Pass the acting
    CorporateAccount.id whenever the call is ownership-gated on a reservation."""
    return build_user_headers(account_id, "CorporateBooker")


def make_affiliate_partner_headers(affiliate_id: str) -> dict:
    """For AffiliatePartner (entity_backed:Affiliate). Pass the acting Affiliate.id
    whenever deciding a farm-out offer addressed to that affiliate."""
    return build_user_headers(affiliate_id, "AffiliatePartner")


def make_chauffeur_headers(chauffeur_id: str) -> dict:
    """For Chauffeur (entity_backed:Chauffeur). Pass the acting Chauffeur.id
    whenever dispatching/completing own trip, posting wait events, or clocking."""
    return build_user_headers(chauffeur_id, "Chauffeur")
