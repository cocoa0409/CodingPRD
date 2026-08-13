"""Pre-built role headers for every role in the PRD.

Opaque roles (CommissionAdmin, SanctioningReviewer, CvbAuditor, Any) use shared
constants. Entity-backed roles (TeamRep, Official, Volunteer, HotelManager,
VenueManager) have per-instance builders: pass the actual entity id whenever the
call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for any call whose outcome does
# not depend on the caller owning the subject resource.
TEST_USERS = {
    "admin_headers": build_user_headers("ops-admin-1", "CommissionAdmin"),
    "admin2_headers": build_user_headers("ops-admin-2", "CommissionAdmin"),
    "reviewer_headers": build_user_headers("rev-9", "SanctioningReviewer"),
    "cvb_headers": build_user_headers("cvb-7", "CvbAuditor"),
    "any_headers": build_user_headers("reader-1", "Any"),
    # Entity-backed fallbacks for non-ownership-gated calls only.
    "teamrep_headers": build_user_headers("test-teamrep-1", "TeamRep"),
    "official_headers": build_user_headers("test-official-1", "Official"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "hotel_manager_headers": build_user_headers("test-hotelmanager-1", "HotelManager"),
    "venue_manager_headers": build_user_headers("test-venuemanager-1", "VenueManager"),
}


# Per-instance builders — required for every entity_backed role whenever the
# call is ownership-gated (X-User-ID must equal the owned entity's id).
def make_teamrep_headers(team_id: str) -> dict:
    """TeamRep headers; pass the acting Team's id."""
    return build_user_headers(team_id, "TeamRep")


def make_official_headers(official_id: str) -> dict:
    """Official headers; pass the acting Official's id."""
    return build_user_headers(official_id, "Official")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Volunteer headers; pass the acting Volunteer's id."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_hotel_manager_headers(hotel_block_id: str) -> dict:
    """HotelManager headers; pass the operated HotelBlock's id."""
    return build_user_headers(hotel_block_id, "HotelManager")


def make_venue_manager_headers(venue_id: str) -> dict:
    """VenueManager headers; pass the operated Venue's id."""
    return build_user_headers(venue_id, "VenueManager")
