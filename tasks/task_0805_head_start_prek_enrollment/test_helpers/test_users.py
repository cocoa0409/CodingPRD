"""Pre-built role headers for every role in the PRD (§2.1).

Three of the four roles (ProgramAdmin, EnrollmentSpecialist, FamilyServicesWorker)
carry an opaque identity: X-User-ID is never compared to a persisted entity, so a
shared constant is always safe. The fourth role, Family, is entity-backed: for
guardian-owned operations ownership is checked by comparing X-User-ID to the owning
Family.id, so ownership-gated calls MUST use make_family_headers(family_id) with the
real Family id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-programadmin-1", "ProgramAdmin"),
    "enrollment_specialist_headers": build_user_headers("test-specialist-1", "EnrollmentSpecialist"),
    "family_services_worker_headers": build_user_headers("test-fsworker-1", "FamilyServicesWorker"),
    # Entity-backed fallback: only for tests that do NOT exercise ownership.
    "family_headers": build_user_headers("test-family-unknown", "Family"),
}


# Per-instance builder — required for the entity-backed Family role.
def make_family_headers(user_id: str) -> dict:
    """For Family (entity_backed:Family). Pass the actual Family.id as user_id
    whenever the call is ownership-gated (accept/decline offer, submit/withdraw
    application, withdraw enrollment)."""
    return build_user_headers(user_id, "Family")


def make_program_admin_headers(user_id: str = "test-programadmin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_enrollment_specialist_headers(user_id: str = "test-specialist-1") -> dict:
    return build_user_headers(user_id, "EnrollmentSpecialist")


def make_family_services_worker_headers(user_id: str = "test-fsworker-1") -> dict:
    return build_user_headers(user_id, "FamilyServicesWorker")
