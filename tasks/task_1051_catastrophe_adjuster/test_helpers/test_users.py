"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - DeskExaminer, LicensingAdmin, BillingManager are opaque roles: the shared
#    constant is the canonical form (X-User-ID is not compared to any entity id).
#  - FieldAdjuster and QAReviewer are entity_backed:Adjuster. The shared constant
#    is a fallback ONLY for tests that do not exercise ownership (e.g. RBAC 403s).
#    Ownership-gated calls MUST use the per-instance builders below with the real
#    Adjuster id.
TEST_USERS = {
    "desk_examiner_headers": build_user_headers("desk-examiner-1", "DeskExaminer"),
    "licensing_admin_headers": build_user_headers("licensing-admin-1", "LicensingAdmin"),
    "billing_manager_headers": build_user_headers("billing-manager-1", "BillingManager"),
    "field_adjuster_headers": build_user_headers("field-adjuster-1", "FieldAdjuster"),
    "qa_reviewer_headers": build_user_headers("qa-reviewer-1", "QAReviewer"),
}


def make_field_adjuster_headers(user_id: str) -> dict:
    """For FieldAdjuster (entity_backed:Adjuster). Pass the acting Adjuster.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FieldAdjuster")


def make_qa_reviewer_headers(user_id: str) -> dict:
    """For QAReviewer (entity_backed:Adjuster). Pass the acting Adjuster.id; the
    segregation-of-duties rule compares it to the report's authoring adjuster."""
    return build_user_headers(user_id, "QAReviewer")
