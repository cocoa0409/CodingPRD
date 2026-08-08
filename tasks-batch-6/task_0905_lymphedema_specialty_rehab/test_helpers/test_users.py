"""Pre-built role headers for every role in the Lymphedema & Specialty Rehab API.

Three of the four roles (Authorizer, DMECoordinator, ClinicAdmin) carry an opaque
X-User-ID that the server records but never compares to any entity id. The
Clinician role's X-User-ID is the id of a Therapist record, but no operation in
the contract rejects a request on the basis of that ownership match, so a shared
constant is sufficient for every scenario here. A per-instance builder is still
provided for completeness.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "clinician_headers": build_user_headers("test-clinician-1", "Clinician"),
    "authorizer_headers": build_user_headers("test-authorizer-1", "Authorizer"),
    "dme_coordinator_headers": build_user_headers("test-dme-1", "DMECoordinator"),
    "clinic_admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
}


def make_clinician_headers(therapist_id: str) -> dict:
    """For the Clinician role (entity_backed:Therapist). Pass the acting
    Therapist.id as user_id."""
    return build_user_headers(therapist_id, "Clinician")


def make_authorizer_headers(user_id: str = "test-authorizer-1") -> dict:
    return build_user_headers(user_id, "Authorizer")


def make_dme_coordinator_headers(user_id: str = "test-dme-1") -> dict:
    return build_user_headers(user_id, "DMECoordinator")


def make_clinic_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ClinicAdmin")
