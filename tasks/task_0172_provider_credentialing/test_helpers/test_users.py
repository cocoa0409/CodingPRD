"""Pre-built role headers for every role in the PRD.

All six roles use an opaque identity model: X-User-ID is an operator string that
is never the primary key of any persisted entity. The server records it where the
workflow demands an accountability anchor (initiated_by_user_id, chair_user_id,
voter_user_id), so tests that exercise segregation-of-duties or the chair tie-break
MUST control the exact X-User-ID string. The make_*_headers builders below construct
headers under a caller-chosen user_id for that purpose.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — convenient defaults for tests that do not depend on a
# particular operator identity (e.g. permission/validation/not-found checks).
TEST_USERS = {
    "system_admin_headers": build_user_headers("admin-1", "SystemAdmin"),
    "credentialing_specialist_headers": build_user_headers("spec-1", "CredentialingSpecialist"),
    "medical_director_headers": build_user_headers("md-1", "MedicalDirector"),
    "peer_reviewer_headers": build_user_headers("rev-1", "PeerReviewer"),
    "enrollment_coordinator_headers": build_user_headers("enr-1", "EnrollmentCoordinator"),
    "compliance_officer_headers": build_user_headers("comp-1", "ComplianceOfficer"),
}


def make_system_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "SystemAdmin")


def make_specialist_headers(user_id: str = "spec-1") -> dict:
    return build_user_headers(user_id, "CredentialingSpecialist")


def make_medical_director_headers(user_id: str = "md-1") -> dict:
    return build_user_headers(user_id, "MedicalDirector")


def make_peer_reviewer_headers(user_id: str = "rev-1") -> dict:
    return build_user_headers(user_id, "PeerReviewer")


def make_enrollment_coordinator_headers(user_id: str = "enr-1") -> dict:
    return build_user_headers(user_id, "EnrollmentCoordinator")


def make_compliance_officer_headers(user_id: str = "comp-1") -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_headers(role: str, user_id: str) -> dict:
    """Generic builder for an arbitrary (possibly unknown) role + user_id."""
    return build_user_headers(user_id, role)
