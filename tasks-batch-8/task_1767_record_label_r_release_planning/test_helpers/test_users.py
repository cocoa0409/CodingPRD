"""Pre-built role headers for every role in the PRD.

LabelAdmin, AnRManager, FinanceController, MarketingManager are opaque identities:
X-User-ID is not tied to any persisted entity. ArtistPortal is entity-backed by
Artist (X-User-ID is the acting Artist's id); ownership-gated calls MUST use
the per-instance builder with the real Artist.id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "label_admin_headers": build_user_headers("test-label-admin-1", "LabelAdmin"),
    "anr_manager_headers": build_user_headers("test-anr-1", "AnRManager"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceController"),
    "marketing_headers": build_user_headers("test-marketing-1", "MarketingManager"),
    # entity_backed:Artist — shared constant is a fallback for non-ownership tests only.
    "artist_portal_headers": build_user_headers("test-artist-1", "ArtistPortal"),
}


def make_label_admin_headers(user_id: str = "test-label-admin-1") -> dict:
    return build_user_headers(user_id, "LabelAdmin")


def make_anr_manager_headers(user_id: str = "test-anr-1") -> dict:
    return build_user_headers(user_id, "AnRManager")


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceController")


def make_marketing_headers(user_id: str = "test-marketing-1") -> dict:
    return build_user_headers(user_id, "MarketingManager")


def make_artist_portal_headers(artist_id: str) -> dict:
    """For ArtistPortal (entity_backed:Artist). Pass the acting Artist.id
    whenever the call is ownership-gated."""
    return build_user_headers(artist_id, "ArtistPortal")
