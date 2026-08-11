"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque-identity roles (CommitteeChair, RegistrarOfficer,
# VenueCoordinator, Vendor): X-User-ID is an opaque operator identifier (PRD §2.1).
TEST_USERS = {
    "committee_chair_headers": build_user_headers("test-chair-1", "CommitteeChair"),
    "registrar_headers": build_user_headers("test-registrar-1", "RegistrarOfficer"),
    "venue_coordinator_headers": build_user_headers("test-coordinator-1", "VenueCoordinator"),
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    # Graduate is entity-backed; this fallback is only for tests that never
    # exercise an ownership-gated call.
    "graduate_headers": build_user_headers("test-graduate-1", "Graduate"),
}


# Segregation-of-duties operator pairs (PRD §2.7) and per-instance builders.

def make_committee_chair_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommitteeChair")


def make_registrar_headers(user_id: str) -> dict:
    """RegistrarOfficer with a specific operator id (batch create/release SoD)."""
    return build_user_headers(user_id, "RegistrarOfficer")


def make_coordinator_headers(user_id: str) -> dict:
    """VenueCoordinator with a specific operator id (strike record/waive and
    accommodation approve/fulfill SoD)."""
    return build_user_headers(user_id, "VenueCoordinator")


def make_vendor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Vendor")


def make_graduate_headers(user_id: str) -> dict:
    """Graduate is entity-backed: pass the actual Graduate.id as user_id for
    every ownership-gated call (PRD §2.1)."""
    return build_user_headers(user_id, "Graduate")
