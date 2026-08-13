"""Pre-built role headers for every role in the PRD (§2.1).

PRD §2.1: for ComplianceOfficer, EnrollmentSpecialist, and PayerRepresentative
the X-User-ID is an opaque operator identifier; for Provider it must equal the
acting Provider's id (ownership checks compare against it).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. The Provider constant is a fallback for non-ownership reads only.
TEST_USERS = {
    "compliance_officer_headers": build_user_headers("officer-1", "ComplianceOfficer"),
    "enrollment_specialist_headers": build_user_headers("specialist-1", "EnrollmentSpecialist"),
    "payer_representative_headers": build_user_headers("payer-rep-1", "PayerRepresentative"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
}


def make_compliance_officer_headers(user_id: str) -> dict:
    """ComplianceOfficer with a specific opaque identity (e.g. for the
    segregation-of-duties check on roster reconcile)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_enrollment_specialist_headers(user_id: str) -> dict:
    """EnrollmentSpecialist with a specific opaque identity (e.g. the roster
    submitter whose id is recorded as submitted_by_user_id)."""
    return build_user_headers(user_id, "EnrollmentSpecialist")


def make_payer_representative_headers(user_id: str) -> dict:
    """PayerRepresentative with a specific opaque identity."""
    return build_user_headers(user_id, "PayerRepresentative")


def make_provider_headers(provider_id: str) -> dict:
    """Provider (entity-backed identity). Pass the actual Provider.id whenever
    the call is ownership-gated (CAQH attestation)."""
    return build_user_headers(provider_id, "Provider")
