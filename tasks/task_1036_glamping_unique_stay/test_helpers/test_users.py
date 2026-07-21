"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#   PermitReviewer and PlatformAdmin are opaque operator roles -> X-User-ID is
#   never matched to an entity id, so the shared constant is the canonical form.
#   Host and Guest are entity_backed: the shared constant is only a fallback for
#   tests that do NOT exercise resource ownership (e.g., 403-by-role, missing
#   resource). Ownership-gated calls MUST use the per-instance builders threaded
#   with the real entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "permit_reviewer_headers": build_user_headers("reviewer-1", "PermitReviewer"),
    "host_headers": build_user_headers("host-fallback-1", "Host"),
    "guest_headers": build_user_headers("guest-fallback-1", "Guest"),
}


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    """PlatformAdmin is opaque; X-User-ID is never matched to an entity id."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_permit_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    """PermitReviewer is opaque; X-User-ID is never matched to an entity id."""
    return build_user_headers(user_id, "PermitReviewer")


def make_host_headers(user_id: str) -> dict:
    """For Host (entity_backed:Host). Pass the actual Host.id as user_id whenever
    the call is ownership-gated (listing/permit/rate/add-on/slot mutations and
    host-side booking lifecycle on own listings)."""
    return build_user_headers(user_id, "Host")


def make_guest_headers(user_id: str) -> dict:
    """For Guest (entity_backed:Guest). Pass the actual Guest.id as user_id
    whenever the call is ownership-gated (booking request/attach/cancel/review on
    own bookings)."""
    return build_user_headers(user_id, "Guest")


# Headers carrying NO recognized role -> exercises the ERR_UNAUTHENTICATED path
# (PRD §2.1: missing/unknown role). Content-Type only, no X-User-ID/X-User-Role.
NO_AUTH_HEADERS: dict = {"Content-Type": "application/json"}
