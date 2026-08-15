"""Pre-built role headers for every role in the PRD (§2.1).

RegisteredRep is entity-backed: its X-User-ID must equal the Representative
record's id on ownership-gated calls, so use make_rep_headers(rep["id"]) for
any call the rep makes on its own enrollments / attestations.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "admin_headers": build_user_headers("ta-1", "TrainingAdmin"),
    "admin2_headers": build_user_headers("ta-2", "TrainingAdmin"),
    "officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
    "officer2_headers": build_user_headers("co-2", "ComplianceOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership
    # tests only (e.g., RBAC denial checks where no specific rep is needed).
    "rep_headers": build_user_headers("rep-opaque-1", "RegisteredRep"),
    "auditor_headers": build_user_headers("aud-1", "Auditor"),
}


def make_rep_headers(user_id: str) -> dict:
    """For RegisteredRep (entity_backed: Representative). Pass the actual
    Representative.id as user_id whenever the call is ownership-gated
    (enrollment start/complete/reattempt, attestation attest)."""
    return build_user_headers(user_id, "RegisteredRep")


def make_admin_headers(user_id: str) -> dict:
    """TrainingAdmin with a specific operator id (opaque; used when a test
    needs a distinct author identity for segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "TrainingAdmin")


def make_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific operator id (opaque; used when a
    test needs the approver identity pinned, e.g., SoD scenarios)."""
    return build_user_headers(user_id, "ComplianceOfficer")
