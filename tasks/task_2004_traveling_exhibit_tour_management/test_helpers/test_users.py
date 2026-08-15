"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are identity-opaque: X-User-ID is never compared against any
resource's id, so shared constants are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "tour_manager_headers": build_user_headers("test-tour-manager-1", "TourManager"),
    "venue_registrar_headers": build_user_headers("test-venue-registrar-1", "VenueRegistrar"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "shipper_headers": build_user_headers("test-shipper-1", "Shipper"),
    "insurer_headers": build_user_headers("test-insurer-1", "Insurer"),
}
