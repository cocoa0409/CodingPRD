"""Pre-built role headers for every role in the PRD.

All four roles (Applicant, PlanReviewer, Inspector, FireMarshal) carry an opaque
identity: X-User-ID is never resolved to a stored entity id. The single ownership
check compares the acting Applicant's X-User-ID against a permit application's
supplied `applicant_user_id`, so applicant-owned actions must present an X-User-ID
equal to that value — use make_applicant_headers(applicant_user_id) for those.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for role-based tests and any test not exercising
# applicant ownership.
TEST_USERS = {
    "applicant_headers": build_user_headers("applicant-shared", "Applicant"),
    "plan_reviewer_headers": build_user_headers("plan-reviewer-1", "PlanReviewer"),
    "inspector_headers": build_user_headers("inspector-1", "Inspector"),
    "fire_marshal_headers": build_user_headers("fire-marshal-1", "FireMarshal"),
}


# Per-instance builders.
def make_applicant_headers(applicant_user_id: str) -> dict:
    """Applicant identity. Pass the application's `applicant_user_id` so the
    ownership check (X-User-ID == application.applicant_user_id) passes on the
    applicant-owned actions (submit, pay-fee, resubmit-corrections)."""
    return build_user_headers(applicant_user_id, "Applicant")


def make_plan_reviewer_headers(user_id: str = "plan-reviewer-1") -> dict:
    return build_user_headers(user_id, "PlanReviewer")


def make_inspector_headers(user_id: str = "inspector-1") -> dict:
    return build_user_headers(user_id, "Inspector")


def make_fire_marshal_headers(user_id: str = "fire-marshal-1") -> dict:
    return build_user_headers(user_id, "FireMarshal")
