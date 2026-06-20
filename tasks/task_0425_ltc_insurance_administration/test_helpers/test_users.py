"""Pre-built role headers for every role in the PRD.

Four roles (Underwriter, ClaimsExaminer, CareAssessor, Regulator) carry an
opaque identity: X-User-ID is an operator identifier never compared to any
entity id, so the shared-constant form is canonical for them.

The Policyholder role is entity-backed: X-User-ID must equal the acting
Policyholder record's id whenever an ownership check applies (paying an
invoice). Such calls MUST use make_policyholder_headers(policyholder_id) with
the real id; the shared constant is only a fallback for tests that do not
exercise policyholder ownership.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "claims_examiner_headers": build_user_headers("test-examiner-1", "ClaimsExaminer"),
    "care_assessor_headers": build_user_headers("test-assessor-1", "CareAssessor"),
    "regulator_headers": build_user_headers("test-regulator-1", "Regulator"),
    # Fallback only — for ownership-gated calls thread make_policyholder_headers(id).
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
}


def make_policyholder_headers(user_id: str) -> dict:
    """For Policyholder (entity_backed:Policyholder). Pass the actual
    Policyholder.id as user_id whenever the call is ownership-gated
    (e.g., POST /premium-invoices/{id}/pay)."""
    return build_user_headers(user_id, "Policyholder")
