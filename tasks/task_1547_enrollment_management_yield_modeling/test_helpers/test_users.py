"""Pre-built role headers for every role in the PRD.

SystemAdmin, EnrollmentManager, AdmissionsOfficer, ApplicationReader, and
FinancialAidOfficer are opaque identities: X-User-ID is not tied to any
persisted entity. Applicant is entity-backed: X-User-ID must equal the acting
Applicant record's id on every ownership-gated call, so those calls MUST use
make_applicant_headers(applicant_id) with the real id. ApplicationReader
submission is pinned to the review's reader_id, so submits MUST use
make_reader_headers(reader_id).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (bad-payload, not-found, or wrong-role checks).
TEST_USERS = {
    "system_admin_headers": build_user_headers("test-sysadmin-1", "SystemAdmin"),
    "enrollment_manager_headers": build_user_headers("test-em-1", "EnrollmentManager"),
    "admissions_officer_headers": build_user_headers("test-ao-1", "AdmissionsOfficer"),
    "financial_aid_officer_headers": build_user_headers("test-fao-1", "FinancialAidOfficer"),
    # entity_backed / identity-pinned roles: shared constants are fallbacks
    # only for tests that never pass an ownership or reviewer check.
    "application_reader_headers": build_user_headers("test-reader-1", "ApplicationReader"),
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


def make_system_admin_headers(user_id: str = "test-sysadmin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_enrollment_manager_headers(user_id: str = "test-em-1") -> dict:
    return build_user_headers(user_id, "EnrollmentManager")


def make_admissions_officer_headers(user_id: str = "test-ao-1") -> dict:
    return build_user_headers(user_id, "AdmissionsOfficer")


def make_financial_aid_officer_headers(user_id: str = "test-fao-1") -> dict:
    return build_user_headers(user_id, "FinancialAidOfficer")


def make_reader_headers(reader_id: str) -> dict:
    """For ApplicationReader submitting a read: pass the review's reader_id
    so X-User-ID equals the reader_id the submission is pinned to."""
    return build_user_headers(reader_id, "ApplicationReader")


def make_applicant_headers(applicant_id: str) -> dict:
    """For Applicant (entity-backed by Applicant). Pass the acting
    Applicant.id whenever the call is ownership-gated."""
    return build_user_headers(applicant_id, "Applicant")
