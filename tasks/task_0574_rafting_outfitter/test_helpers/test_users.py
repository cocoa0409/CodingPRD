"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - OutfitterManager, Reservationist, SafetyOfficer carry opaque X-User-ID
#    identifiers not tied to any persisted entity (PRD §2.1), so the shared
#    constant is the canonical form for these roles.
#  - Guest is entity_backed (X-User-ID == the acting Guest's id); the shared
#    constant is a fallback for non-ownership tests only. Ownership-gated
#    waiver signing MUST use make_guest_headers(guest_id).
TEST_USERS = {
    "outfitter_manager_headers": build_user_headers("mgr-1", "OutfitterManager"),
    "reservationist_headers": build_user_headers("resv-1", "Reservationist"),
    "safety_officer_headers": build_user_headers("safety-1", "SafetyOfficer"),
    "guest_headers": build_user_headers("guest-shared-1", "Guest"),
}


def make_guest_headers(user_id: str) -> dict:
    """For the Guest role (entity_backed: Guest). Pass the actual Guest.id as
    user_id whenever the call is ownership-gated (waiver signing)."""
    return build_user_headers(user_id, "Guest")
