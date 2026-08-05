"""Pre-built role headers for every role in the PRD.

The Applicant, PermitClerk, and AgencyReviewer roles are opaque operator
identifiers; the Inspector role is entity_backed:Inspector (X-User-ID is the
acting Inspector's id). Segregation-of-duties tests need to control the exact
X-User-ID recorded by reviewers vs the approving clerk, so per-instance builders
are provided for those roles too.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for tests that do not exercise identity/ownership.
TEST_USERS = {
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "clerk_headers": build_user_headers("test-clerk-1", "PermitClerk"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "AgencyReviewer"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_applicant_headers(user_id: str) -> dict:
    """Headers for the Applicant role (opaque X-User-ID)."""
    return build_user_headers(user_id, "Applicant")


def make_clerk_headers(user_id: str) -> dict:
    """Headers for the PermitClerk role (opaque X-User-ID). Control the id when a
    segregation-of-duties check compares the clerk to a reviewer's recorded_by."""
    return build_user_headers(user_id, "PermitClerk")


def make_reviewer_headers(user_id: str) -> dict:
    """Headers for the AgencyReviewer role. The supplied id is stored as the
    review's recorded_by, so control it for segregation-of-duties scenarios."""
    return build_user_headers(user_id, "AgencyReviewer")


def make_inspector_headers(inspector_id: str) -> dict:
    """Headers for the Inspector role (entity_backed:Inspector). Pass the actual
    Inspector entity's id so ownership checks on record-result succeed."""
    return build_user_headers(inspector_id, "Inspector")
