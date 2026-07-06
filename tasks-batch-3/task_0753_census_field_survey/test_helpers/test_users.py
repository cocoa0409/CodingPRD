"""Pre-built role headers for every role in the PRD.

Three roles carry an opaque identity (SurveyAdmin, FieldSupervisor, QCReviewer):
their X-User-ID is never compared against a persisted entity. The Enumerator role
is entity-backed: its X-User-ID must be the id of the acting Enumerator record, so
ownership-gated calls MUST use make_enumerator_headers(enumerator_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# enumerator ownership (400s, 403 RBAC denials, 404s).
TEST_USERS = {
    "survey_admin_headers": build_user_headers("test-admin-1", "SurveyAdmin"),
    "field_supervisor_headers": build_user_headers("test-supervisor-1", "FieldSupervisor"),
    "qc_reviewer_headers": build_user_headers("test-qc-1", "QCReviewer"),
    # Fallback for non-ownership Enumerator tests only. Ownership-gated attempt /
    # response calls MUST use make_enumerator_headers(enumerator_id) instead.
    "enumerator_headers": build_user_headers("test-enumerator-1", "Enumerator"),
}


def make_enumerator_headers(user_id: str) -> dict:
    """For the Enumerator role (entity-backed on Enumerator). Pass the actual
    Enumerator.id as user_id whenever the call is ownership-gated (logging an
    attempt or capturing a response for that enumerator's assigned case)."""
    return build_user_headers(user_id, "Enumerator")
