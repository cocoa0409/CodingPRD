"""Pre-built role headers for every role in the PRD.

VenueAdmin, SponsorshipSales, ActivationManager, and FinanceManager carry
opaque identities: X-User-ID is not tied to any persisted entity.
SponsorContact is entity-backed by SponsorAccount (X-User-ID is the sponsor
account's id); ownership-gated calls MUST use make_sponsor_contact_headers()
with the real SponsorAccount.id, never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "venue_admin_headers": build_user_headers("test-venue-admin-1", "VenueAdmin"),
    "sales_headers": build_user_headers("test-sales-1", "SponsorshipSales"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceManager"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "sponsor_contact_headers": build_user_headers("test-sponsor-contact-1",
                                                  "SponsorContact"),
}


def make_venue_admin_headers(user_id: str = "test-venue-admin-1") -> dict:
    return build_user_headers(user_id, "VenueAdmin")


def make_sales_headers(user_id: str = "test-sales-1") -> dict:
    return build_user_headers(user_id, "SponsorshipSales")


def make_activation_headers(user_id: str) -> dict:
    """ActivationManager is opaque, but evidence review is four-eyes: the
    reviewing X-User-ID must differ from the submission's
    submitted_by_user_id. Pass distinct ids for submitter vs reviewer."""
    return build_user_headers(user_id, "ActivationManager")


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FinanceManager")


def make_sponsor_contact_headers(sponsor_id: str) -> dict:
    """For SponsorContact (entity_backed:SponsorAccount). Pass the actual
    SponsorAccount.id as sponsor_id whenever the call is ownership-gated
    (countersign, report acknowledge, scoped reads)."""
    return build_user_headers(sponsor_id, "SponsorContact")
