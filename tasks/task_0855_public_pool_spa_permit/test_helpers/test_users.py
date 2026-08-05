"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Opaque identifiers used throughout the suite. Only the Operator role's
# X-User-ID is compared against a stored entity id.
INSPECTOR_ONE_ID = "insp-1"
INSPECTOR_TWO_ID = "insp-2"
PLAN_REVIEWER_ONE_ID = "pr-1"
PLAN_REVIEWER_TWO_ID = "pr-2"
ADMIN_ONE_ID = "admin-1"
ADMIN_TWO_ID = "admin-2"
ANONYMOUS_ID = "public-1"

# Shared constants — safe for the opaque roles, and for Operator-role tests
# that do not exercise ownership (payload errors, missing-resource lookups).
TEST_USERS = {
    "anonymous_headers": build_user_headers(ANONYMOUS_ID, "Anonymous"),
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
    "inspector_headers": build_user_headers(INSPECTOR_ONE_ID, "Inspector"),
    "inspector_two_headers": build_user_headers(INSPECTOR_TWO_ID, "Inspector"),
    "plan_reviewer_headers": build_user_headers(PLAN_REVIEWER_ONE_ID, "PlanReviewer"),
    "plan_reviewer_two_headers": build_user_headers(PLAN_REVIEWER_TWO_ID, "PlanReviewer"),
    "admin_headers": build_user_headers(ADMIN_ONE_ID, "HealthAuthorityAdmin"),
    "admin_two_headers": build_user_headers(ADMIN_TWO_ID, "HealthAuthorityAdmin"),
}

ANON = TEST_USERS["anonymous_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
INSPECTOR_TWO = TEST_USERS["inspector_two_headers"]
PLAN_REVIEWER = TEST_USERS["plan_reviewer_headers"]
PLAN_REVIEWER_TWO = TEST_USERS["plan_reviewer_two_headers"]
ADMIN = TEST_USERS["admin_headers"]
ADMIN_TWO = TEST_USERS["admin_two_headers"]


def make_operator_headers(operator_id: str) -> dict:
    """Headers for the Operator role.

    The Operator role's X-User-ID is the id of the acting Operator record, so
    every ownership-gated call must pass the real operator id here.
    """
    return build_user_headers(operator_id, "Operator")


def make_inspector_headers(user_id: str) -> dict:
    """Headers for an Inspector with a specific opaque field-inspector id."""
    return build_user_headers(user_id, "Inspector")


def make_plan_reviewer_headers(user_id: str) -> dict:
    """Headers for a PlanReviewer with a specific opaque engineer id."""
    return build_user_headers(user_id, "PlanReviewer")


def make_admin_headers(user_id: str) -> dict:
    """Headers for a HealthAuthorityAdmin with a specific opaque officer id."""
    return build_user_headers(user_id, "HealthAuthorityAdmin")


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role string — used by authentication tests."""
    return build_user_headers(user_id, role)
