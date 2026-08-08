"""Pre-built role headers for every role in the PRD.

IntakeCoordinator, ClinicalDirector, and BillingSpecialist have opaque identity
(X-User-ID is not compared to any entity). Therapist is entity_backed: any
ownership-gated call must carry the acting therapist's own id as X-User-ID, so
use make_therapist_headers(therapist_id) for those calls.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "intake_headers": build_user_headers("intake-op-1", "IntakeCoordinator"),
    # Shared Therapist header: safe ONLY for non-ownership scenarios (e.g. a 403
    # authorization check). Ownership-gated calls must use make_therapist_headers.
    "therapist_headers": build_user_headers("therapist-op-1", "Therapist"),
    "clinical_headers": build_user_headers("clinical-op-1", "ClinicalDirector"),
    "billing_headers": build_user_headers("billing-op-1", "BillingSpecialist"),
}


def make_therapist_headers(therapist_id: str) -> dict:
    """For the Therapist role (entity_backed:Therapist). Pass the actual
    Therapist.id as X-User-ID whenever the call is ownership-gated (scheduling,
    completing, cancelling, enrolling, or writing/signing a progress note)."""
    return build_user_headers(therapist_id, "Therapist")


def make_role_headers(user_id: str, role: str) -> dict:
    """Arbitrary role header, for auth/authorization negative tests."""
    return build_user_headers(user_id, role)
