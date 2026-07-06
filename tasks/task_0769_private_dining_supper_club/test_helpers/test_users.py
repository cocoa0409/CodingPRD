"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, CustomerService), and for
# tests that do not exercise ownership. Entity-backed roles (VenueManager/Chef/Guest)
# MUST use their make_*_headers(entity_id) builders for ownership-gated calls.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "customer_service_headers": build_user_headers("test-cs-1", "CustomerService"),
    # Fallback for non-ownership tests only.
    "guest_headers": build_user_headers("test-guest-1", "Guest"),
    "venue_manager_headers": build_user_headers("test-venue-1", "VenueManager"),
    "chef_headers": build_user_headers("test-chef-1", "Chef"),
}


def make_guest_headers(user_id: str) -> dict:
    """For the Guest role (entity_backed:Guest). Pass the actual Guest.id as user_id
    whenever the call is ownership-gated (booking create/pay/cancel, waitlist join/withdraw)."""
    return build_user_headers(user_id, "Guest")


def make_venue_manager_headers(user_id: str) -> dict:
    """For the VenueManager role (entity_backed:Venue). Pass the actual Venue.id as user_id
    whenever the call is ownership-gated on that venue's events."""
    return build_user_headers(user_id, "VenueManager")


def make_chef_headers(user_id: str) -> dict:
    """For the Chef role (entity_backed:Chef). Pass the actual Chef.id as user_id whenever
    the call is ownership-gated on that chef's events/availability."""
    return build_user_headers(user_id, "Chef")
