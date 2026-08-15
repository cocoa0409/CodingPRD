"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# entity-backed identity resolution.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "state_reviewer_headers": build_user_headers("reviewer-1", "StateAgencyReviewer"),
    "funder_contact_headers": build_user_headers("funder-9", "FunderContact"),
    # Fallbacks for entity-backed roles — only valid in tests where the call is
    # expected to fail authentication/authorization (no real Staff row matches).
    "site_director_headers": build_user_headers("test-director-1", "SiteDirector"),
    "frontline_staff_headers": build_user_headers("test-frontline-1", "FrontlineStaff"),
}


def make_site_director_headers(staff_id: str) -> dict:
    """SiteDirector is entity-backed: X-User-ID must be the id of an ACTIVE
    Staff row whose position is DIRECTOR (PRD 2.1). Pass the real Staff.id."""
    return build_user_headers(staff_id, "SiteDirector")


def make_frontline_staff_headers(staff_id: str) -> dict:
    """FrontlineStaff is entity-backed: X-User-ID must be the id of an ACTIVE
    Staff row whose position is FRONTLINE (PRD 2.1). Pass the real Staff.id."""
    return build_user_headers(staff_id, "FrontlineStaff")


def make_reviewer_headers(user_id: str) -> dict:
    """StateAgencyReviewer is opaque; any operator identifier is accepted."""
    return build_user_headers(user_id, "StateAgencyReviewer")


def make_funder_contact_headers(user_id: str) -> dict:
    """FunderContact is opaque; any operator identifier is accepted."""
    return build_user_headers(user_id, "FunderContact")
