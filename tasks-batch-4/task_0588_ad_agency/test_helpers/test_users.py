"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   AgencyAdmin's X-User-ID is an opaque operator identifier that the server never
#   compares to any entity id, so the shared constant is the canonical form.
#   The four other roles are entity-backed: use the per-instance builders below and
#   pass the real StaffMember.id / Client.id.  The shared constants for those roles
#   are only safe on calls that never reach an ownership check.
TEST_USERS = {
    "agency_admin_headers": build_user_headers("test-agency-admin-1", "AgencyAdmin"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "creative_lead_headers": build_user_headers("test-creative-lead-1", "CreativeLead"),
    "media_buyer_headers": build_user_headers("test-media-buyer-1", "MediaBuyer"),
    "client_reviewer_headers": build_user_headers("test-client-reviewer-1", "ClientReviewer"),
}

# A request carrying neither X-User-ID nor X-User-Role (PRD §2.1).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_agency_admin_headers(user_id: str = "test-agency-admin-1") -> dict:
    """AgencyAdmin — X-User-ID is opaque and tied to no persisted entity."""
    return build_user_headers(user_id, "AgencyAdmin")


def make_account_manager_headers(staff_id: str) -> dict:
    """AccountManager — X-User-ID is the acting StaffMember's id."""
    return build_user_headers(staff_id, "AccountManager")


def make_creative_lead_headers(staff_id: str) -> dict:
    """CreativeLead — X-User-ID is the acting StaffMember's id."""
    return build_user_headers(staff_id, "CreativeLead")


def make_media_buyer_headers(staff_id: str) -> dict:
    """MediaBuyer — X-User-ID is the acting StaffMember's id."""
    return build_user_headers(staff_id, "MediaBuyer")


def make_client_reviewer_headers(client_id: str) -> dict:
    """ClientReviewer — X-User-ID is the acting Client's id (the advertiser itself)."""
    return build_user_headers(client_id, "ClientReviewer")
