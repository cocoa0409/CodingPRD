"""Pre-built role headers for every role in the PRD.

Provider is entity-backed: X-User-ID is the acting Provider's id. Every other
role (PlanAdmin, EditLibrarian, EditApprover, Reviewer, SeniorReviewer,
DisputeAdjudicator, PaymentIntegrityAnalyst) is opaque: X-User-ID is an
operator identifier never compared to any entity's id. Ownership-gated calls
MUST use make_provider_headers(provider_id) with the real entity id; SoD and
reviewer-accountability tests use the per-user builders for the opaque roles.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "plan_admin_headers": build_user_headers("admin-1", "PlanAdmin"),
    "librarian_headers": build_user_headers("librarian-1", "EditLibrarian"),
    "approver_headers": build_user_headers("approver-1", "EditApprover"),
    "reviewer_headers": build_user_headers("rev-1", "Reviewer"),
    "senior_reviewer_headers": build_user_headers("senior-1", "SeniorReviewer"),
    "adjudicator_headers": build_user_headers("adj-1", "DisputeAdjudicator"),
    "analyst_headers": build_user_headers("analyst-1", "PaymentIntegrityAnalyst"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


def make_plan_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlanAdmin")


def make_librarian_headers(user_id: str) -> dict:
    """For EditLibrarian (opaque). Pass distinct ids for SoD scenarios."""
    return build_user_headers(user_id, "EditLibrarian")


def make_approver_headers(user_id: str) -> dict:
    """For EditApprover (opaque). Pass distinct ids for SoD scenarios."""
    return build_user_headers(user_id, "EditApprover")


def make_reviewer_headers(user_id: str) -> dict:
    """For Reviewer (opaque). The id must equal the task's
    assigned_reviewer_user_id when deciding or escalating."""
    return build_user_headers(user_id, "Reviewer")


def make_senior_reviewer_headers(user_id: str) -> dict:
    """For SeniorReviewer (opaque). Same assignee rule as Reviewer on tasks."""
    return build_user_headers(user_id, "SeniorReviewer")


def make_adjudicator_headers(user_id: str) -> dict:
    """For DisputeAdjudicator (opaque). Pass distinct ids for SoD scenarios."""
    return build_user_headers(user_id, "DisputeAdjudicator")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PaymentIntegrityAnalyst")


def make_provider_headers(provider_id: str) -> dict:
    """For Provider (entity_backed:Provider). Pass the acting Provider.id
    whenever the call is ownership-gated (claim create, line add, dispute
    create, dispute submit-info, IBR receive-documents)."""
    return build_user_headers(provider_id, "Provider")
