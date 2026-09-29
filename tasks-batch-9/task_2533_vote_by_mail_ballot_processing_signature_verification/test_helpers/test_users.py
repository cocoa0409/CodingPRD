"""Pre-built role headers for every role named by the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. ElectionsAdmin, ElectionsClerk, CanvassSupervisor and Observer are
# opaque identities, so these are the canonical form for those roles. The
# SignatureReviewer entry is a fallback for tests that do not exercise assignment
# ownership, because a signature decision requires X-User-ID to equal the reviewer id.
TEST_USERS = {
    "elections_admin_headers": build_user_headers("test-admin-1", "ElectionsAdmin"),
    "elections_clerk_headers": build_user_headers("test-clerk-1", "ElectionsClerk"),
    "signature_reviewer_headers": build_user_headers("test-reviewer-1", "SignatureReviewer"),
    "canvass_supervisor_headers": build_user_headers("test-supervisor-1", "CanvassSupervisor"),
    "observer_headers": build_user_headers("test-observer-1", "Observer"),
}


def make_signature_reviewer_headers(reviewer_id: str) -> dict:
    """Headers for a SignatureReviewer. Pass the Reviewer's own id, because a
    signature decision is refused unless X-User-ID equals the review's reviewer_id."""
    return build_user_headers(reviewer_id, "SignatureReviewer")


def make_observer_headers(observer_user_id: str) -> dict:
    """Headers for an Observer. Pass the observer_user_id recorded on the session,
    because check-in is refused when the caller is a different observer."""
    return build_user_headers(observer_user_id, "Observer")


def make_elections_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ElectionsAdmin")


def make_elections_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    return build_user_headers(user_id, "ElectionsClerk")


def make_canvass_supervisor_headers(user_id: str = "test-supervisor-1") -> dict:
    return build_user_headers(user_id, "CanvassSupervisor")
