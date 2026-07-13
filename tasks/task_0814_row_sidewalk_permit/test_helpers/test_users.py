"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the four opaque operator roles and for tests
# that do not exercise Applicant ownership. The Applicant role is entity-backed,
# so its header must carry the actual Applicant.id (see make_applicant_headers).
TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "reviewer_headers": build_user_headers("reviewer-1", "PermitReviewer"),
    "reviewer_2_headers": build_user_headers("reviewer-2", "PermitReviewer"),
    "inspector_headers": build_user_headers("inspector-1", "Inspector"),
    "officer_headers": build_user_headers("officer-1", "EnforcementOfficer"),
}


def make_applicant_headers(user_id: str) -> dict:
    """For the Applicant role (entity_backed:Applicant). Pass the actual
    Applicant.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Applicant")


def make_reviewer_headers(user_id: str) -> dict:
    """PermitReviewer with an explicit operator id — used for the
    segregation-of-duties gate where approver id must differ from issuer id."""
    return build_user_headers(user_id, "PermitReviewer")


def make_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Inspector")


def make_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnforcementOfficer")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
