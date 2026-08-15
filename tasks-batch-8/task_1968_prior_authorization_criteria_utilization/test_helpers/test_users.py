"""Pre-built role headers for every role in the PRD (§2.1).

All eight roles use an opaque operator identifier (PRD §2.1: no persisted user
entity), so the shared constants below are canonical. The make_*_headers
builders exist for tests that must control the exact X-User-ID string — e.g.
segregation-of-duties checks comparing against escalated_by_user_id,
decided_by_user_id, reviewer_id, or md_user_id (PRD §2.8).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "um_admin_headers": build_user_headers("u-admin-1", "UMAdmin"),
    "policy_editor_headers": build_user_headers("u-editor-1", "ClinicalPolicyEditor"),
    "intake_specialist_headers": build_user_headers("u-intake-1", "IntakeSpecialist"),
    "clinical_reviewer_headers": build_user_headers("u-rev-1", "ClinicalReviewer"),
    "medical_director_headers": build_user_headers("u-md-1", "MedicalDirector"),
    "appeals_clerk_headers": build_user_headers("u-clerk-1", "AppealsClerk"),
    "appeals_reviewer_headers": build_user_headers("u-ar-1", "AppealsReviewer"),
    "compliance_officer_headers": build_user_headers("u-co-1", "ComplianceOfficer"),
}


def make_um_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UMAdmin")


def make_policy_editor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClinicalPolicyEditor")


def make_intake_specialist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeSpecialist")


def make_clinical_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClinicalReviewer")


def make_medical_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalDirector")


def make_appeals_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AppealsClerk")


def make_appeals_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AppealsReviewer")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")
