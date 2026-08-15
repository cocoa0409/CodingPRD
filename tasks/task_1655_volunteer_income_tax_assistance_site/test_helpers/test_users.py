"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque SponsorAdmin role, and for the
# entity-backed roles ONLY in tests whose success does not depend on the
# caller owning or staffing the subject resource (e.g. 400-on-bad-payload or
# 404-on-missing-resource calls).
TEST_USERS = {
    "sponsor_admin_headers": build_user_headers("test-sponsor-admin-1", "SponsorAdmin"),
    # Entity-backed fallbacks: these X-User-IDs reference no real Volunteer,
    # so any call whose authorization binds X-User-ID to a Volunteer record
    # MUST use the per-instance builders below instead.
    "site_coordinator_headers": build_user_headers("test-coordinator-1", "SiteCoordinator"),
    "preparer_headers": build_user_headers("test-preparer-1", "Preparer"),
    "quality_reviewer_headers": build_user_headers("test-reviewer-1", "QualityReviewer"),
    "screener_headers": build_user_headers("test-screener-1", "Screener"),
}


def make_site_coordinator_headers(user_id: str) -> dict:
    """SiteCoordinator is entity-backed: pass the acting coordinator
    Volunteer's id; the volunteer must have is_coordinator true and a
    site_id equal to the site being addressed (PRD §2.1)."""
    return build_user_headers(user_id, "SiteCoordinator")


def make_preparer_headers(user_id: str) -> dict:
    """Preparer is entity-backed: pass the acting preparer Volunteer's id.
    Preparer-only lifecycle steps require X-User-ID == return.preparer_id."""
    return build_user_headers(user_id, "Preparer")


def make_quality_reviewer_headers(user_id: str) -> dict:
    """QualityReviewer is entity-backed: pass the acting reviewer Volunteer's
    id; it must differ from the return's preparer_id (segregation of duties)."""
    return build_user_headers(user_id, "QualityReviewer")


def make_screener_headers(user_id: str) -> dict:
    """Screener is entity-backed: pass the acting screener Volunteer's id."""
    return build_user_headers(user_id, "Screener")


def make_sponsor_admin_headers(user_id: str = "test-sponsor-admin-1") -> dict:
    """SponsorAdmin is opaque: its X-User-ID is never compared to any entity."""
    return build_user_headers(user_id, "SponsorAdmin")
