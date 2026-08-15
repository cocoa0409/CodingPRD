"""Pre-built role headers for every role in the PRD.

LeadEstimator, ChiefEstimator, PrequalReviewer, and Anonymous are opaque roles:
X-User-ID is an operator identifier never compared to an entity id (PRD 2.1).
Subcontractor is entity-backed: X-User-ID IS the Subcontractor.id, so any
ownership-gated call must use make_subcontractor_headers(sub["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    # le-100 / ce-900 are the canonical drafter / decider operator ids used by
    # the segregation-of-duties scenarios.
    "lead_estimator_headers": build_user_headers("le-100", "LeadEstimator"),
    "chief_estimator_headers": build_user_headers("ce-900", "ChiefEstimator"),
    "prequal_reviewer_headers": build_user_headers("pqr-100", "PrequalReviewer"),
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "subcontractor_headers": build_user_headers("test-sub-1", "Subcontractor"),
}


def make_lead_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LeadEstimator")


def make_chief_estimator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChiefEstimator")


def make_prequal_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrequalReviewer")


def make_anonymous_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Anonymous")


def make_subcontractor_headers(user_id: str) -> dict:
    """For Subcontractor (entity_backed:Subcontractor). Pass the actual
    Subcontractor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Subcontractor")
