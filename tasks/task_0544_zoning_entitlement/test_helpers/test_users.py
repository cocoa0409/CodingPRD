"""Pre-built role headers for every role in the PRD (§2.1).

Four roles (Admin, Planner, Clerk, Commissioner) carry an *opaque* X-User-ID not
tied to any persisted entity, so shared constants are their canonical form. Only
Applicant is entity_backed: its X-User-ID must equal the acting Applicant.id for
ownership-gated calls (submit, withdraw, plat, pay), so use make_applicant_headers().
"""
from prd_bench_local_runner.testing import build_user_headers

# Default opaque operator ids. planner and commissioner are kept distinct so the
# segregation-of-duties check (§2.9) passes on the happy path.
DEFAULT_PLANNER_ID = "planner-1"
DEFAULT_CLERK_ID = "clerk-1"
DEFAULT_COMMISSIONER_ID = "commish-1"
DEFAULT_ADMIN_ID = "admin-1"

TEST_USERS = {
    "admin_headers": build_user_headers(DEFAULT_ADMIN_ID, "Admin"),
    "planner_headers": build_user_headers(DEFAULT_PLANNER_ID, "Planner"),
    "clerk_headers": build_user_headers(DEFAULT_CLERK_ID, "Clerk"),
    "commissioner_headers": build_user_headers(DEFAULT_COMMISSIONER_ID, "Commissioner"),
    # Fallback constant for Applicant — only for non-ownership tests (e.g. 404/401).
    "applicant_headers": build_user_headers("applicant-fallback", "Applicant"),
}


def make_applicant_headers(user_id: str) -> dict:
    """For Applicant (entity_backed:Applicant). Pass the real Applicant.id whenever
    the call is ownership-gated (submit / withdraw / plat / pay)."""
    return build_user_headers(user_id, "Applicant")


def make_planner_headers(user_id: str) -> dict:
    """Planner with a specific opaque X-User-ID (drives assigned_planner_user_id)."""
    return build_user_headers(user_id, "Planner")


def make_commissioner_headers(user_id: str) -> dict:
    """Commissioner with a specific opaque X-User-ID (compared for segregation of duties)."""
    return build_user_headers(user_id, "Commissioner")


def make_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Clerk")
