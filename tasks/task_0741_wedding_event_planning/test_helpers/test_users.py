"""Pre-built role headers for every role in the PRD (§2.1).

Three roles: Planner (opaque operator — X-User-ID is never matched against any
stored entity id), Client (entity_backed:EventProject — X-User-ID is the acting
EventProject.id) and Vendor (entity_backed:Vendor — X-User-ID is the acting
Vendor.id)."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
#  - Planner is opaque: the shared constant is the canonical form.
#  - Client / Vendor are entity-backed: the shared constant is a FALLBACK ONLY for
#    tests that do NOT exercise ownership (e.g. role-denial / missing-header checks).
#    Ownership-gated calls MUST use make_client_headers(event_id) /
#    make_vendor_headers(vendor_id) with the real owning id.
TEST_USERS = {
    "planner_headers": build_user_headers("test-planner-1", "Planner"),
    "client_headers": build_user_headers("test-client-fallback-1", "Client"),
    "vendor_headers": build_user_headers("test-vendor-fallback-1", "Vendor"),
}


def make_planner_headers(user_id: str = "test-planner-1") -> dict:
    """For the Planner role (opaque identity)."""
    return build_user_headers(user_id, "Planner")


def make_client_headers(event_id: str) -> dict:
    """For the Client role (entity_backed:EventProject). Pass the actual
    EventProject.id as the X-User-ID whenever the call is ownership-gated
    (sign / request-revision / guest create / guest rsvp on the owned event)."""
    return build_user_headers(event_id, "Client")


def make_vendor_headers(vendor_id: str) -> dict:
    """For the Vendor role (entity_backed:Vendor). Pass the actual Vendor.id as the
    X-User-ID whenever the call is ownership-gated (submitting a COI for the owned
    vendor record)."""
    return build_user_headers(vendor_id, "Vendor")
