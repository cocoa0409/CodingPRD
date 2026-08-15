"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, ReviewCoordinator)
# and for tests that do not exercise ownership. For entity-backed roles
# (Reviewer, ChiefReviewer) and for the ownership-scoped Applicant actions,
# prefer the per-instance builders below.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "ReviewCoordinator"),
    # Fallbacks for non-ownership calls only (e.g. 400/404 probes).
    "reviewer_headers": build_user_headers("test-reviewer-1", "Reviewer"),
    "chief_reviewer_headers": build_user_headers("test-chief-1", "ChiefReviewer"),
    "applicant_headers": build_user_headers("app-1", "Applicant"),
}


def make_reviewer_headers(user_id: str) -> dict:
    """For Reviewer (entity-backed): pass the actual Reviewer.id whenever the
    call is ownership-gated (assigned-reviewer or responsible-charge checks)."""
    return build_user_headers(user_id, "Reviewer")


def make_chief_reviewer_headers(user_id: str) -> dict:
    """For ChiefReviewer (entity-backed): pass the actual Reviewer.id of the
    acting chief so the waiver segregation check compares real ids."""
    return build_user_headers(user_id, "ChiefReviewer")


def make_applicant_headers(user_id: str) -> dict:
    """For Applicant: pass the engagement's applicant_contact_id whenever the
    call is applicant-scoped."""
    return build_user_headers(user_id, "Applicant")
