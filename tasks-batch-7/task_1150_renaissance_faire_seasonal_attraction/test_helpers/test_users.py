"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (Performer, Vendor) additionally get per-instance builders:
ownership-gated calls MUST thread the real entity id as X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque coordinator/operator roles — shared constants are canonical.
    "operator_headers": build_user_headers("test-operator-1", "FaireOperator"),
    "cast_director_headers": build_user_headers("test-director-1", "CastDirector"),
    "vendor_coordinator_headers": build_user_headers("test-vendorco-1", "VendorCoordinator"),
    "gate_agent_headers": build_user_headers("test-gate-1", "GateAgent"),
    "volunteer_coordinator_headers": build_user_headers("test-volco-1", "VolunteerCoordinator"),
    # Shared read access designator for GET endpoints.
    "any_headers": build_user_headers("test-any-1", "Any"),
    # Entity-backed / handle roles: fallbacks for non-ownership tests only.
    "performer_headers": build_user_headers("test-performer-1", "Performer"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "guest_headers": build_user_headers("test-guest@example.com", "Guest"),
}


def make_performer_headers(performer_id: str) -> dict:
    """Performer is entity-backed: X-User-ID must be the Performer.id for
    ownership-gated calls (counter/accept on the performer's own contract)."""
    return build_user_headers(performer_id, "Performer")


def make_vendor_headers(vendor_id: str) -> dict:
    """Vendor is entity-backed: X-User-ID must be the Vendor.id for filing and
    for ownership-gated appeals, withdrawals, booth confirms, permit filings."""
    return build_user_headers(vendor_id, "Vendor")


def make_volunteer_headers(volunteer_handle: str) -> dict:
    """Volunteer is an opaque handle recorded as volunteer_handle on sign-up."""
    return build_user_headers(volunteer_handle, "Volunteer")


def make_guest_headers(buyer_email: str) -> dict:
    """Guest's X-User-ID is the buyer email recorded as buyer_email on orders."""
    return build_user_headers(buyer_email, "Guest")
