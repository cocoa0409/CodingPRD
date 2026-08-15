"""Pre-built role headers for every role in the PRD.

Identity semantics per the PRD: TrackOps and SafetyOfficer carry opaque user
ids; Organizer's `X-User-ID` is compared against a booking's stored
`organizer_user_id` on ownership-gated calls (e.g. cancelling one's own
booking), so organizer headers must be built per booking owner; Coach's
`X-User-ID` is the id of the acting Coach entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for calls whose success does not depend on caller
# identity (creation by TrackOps, reads, role-denial probes).
TEST_USERS = {
    "trackops_headers": build_user_headers("test-trackops-1", "TrackOps"),
    "safety_officer_headers": build_user_headers("test-safety-1", "SafetyOfficer"),
    "organizer_headers": build_user_headers("test-organizer-1", "Organizer"),
    # Coach is entity-backed; this shared constant is only for calls (like
    # read-only GETs or role-denial probes) where no ownership check applies.
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
}

# Headers with no role — drives the unauthenticated path.
NO_ROLE_HEADERS = {
    "X-User-ID": "anon-1",
    "Content-Type": "application/json",
}


def make_trackops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TrackOps")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_organizer_headers(user_id: str) -> dict:
    """Organizer calls that are ownership-gated (e.g. cancelling one's own
    booking) MUST pass the booking's organizer_user_id here."""
    return build_user_headers(user_id, "Organizer")


def make_coach_headers(coach_id: str) -> dict:
    """Coach is entity-backed: pass the actual Coach.id whenever the call is
    ownership-gated."""
    return build_user_headers(coach_id, "Coach")
