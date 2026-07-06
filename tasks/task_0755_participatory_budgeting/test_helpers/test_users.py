"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Anonymous, Reviewer, BudgetAdmin),
# and for Resident tests that do not exercise ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("public-anon-1", "Anonymous"),
    "reviewer_headers": build_user_headers("staff-reviewer-1", "Reviewer"),
    "budget_admin_headers": build_user_headers("admin-1", "BudgetAdmin"),
    # Resident is entity_backed: this shared constant is a fallback for
    # non-ownership tests only (e.g. role-denied / 404 cases).
    "resident_headers": build_user_headers("resident-generic-1", "Resident"),
}


def make_resident_headers(user_id: str) -> dict:
    """For Resident (entity_backed:Resident). Pass the actual Resident.id as
    user_id whenever the call is ownership-gated (proposal submit, cost line
    items, ballot entries/cast/withdraw)."""
    return build_user_headers(user_id, "Resident")


def make_anonymous_headers(user_id: str = "public-anon-1") -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_reviewer_headers(user_id: str = "staff-reviewer-1") -> dict:
    return build_user_headers(user_id, "Reviewer")


def make_budget_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "BudgetAdmin")
