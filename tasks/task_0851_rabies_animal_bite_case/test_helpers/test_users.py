"""Pre-built role headers for every role in the PRD.

Five of the six roles carry opaque operator identities: their X-User-ID is never
compared to any entity id. The Owner role is entity_backed — X-User-ID is the id
of the acting Owner entity, so ownership-gated calls MUST use make_owner_headers
with the real owner id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles, and for Owner tests that do not
# exercise a successful ownership path (e.g. wrong-owner 403).
TEST_USERS = {
    "intake_officer_headers": build_user_headers("intake-1", "IntakeOfficer"),
    "epidemiologist_headers": build_user_headers("epi-1", "Epidemiologist"),
    "veterinarian_headers": build_user_headers("vet-1", "Veterinarian"),
    "animal_control_officer_headers": build_user_headers("aco-1", "AnimalControlOfficer"),
    "health_dept_admin_headers": build_user_headers("admin-1", "HealthDeptAdmin"),
    # Owner is entity_backed: shared fallback for non-ownership tests only.
    "owner_headers": build_user_headers("owner-shared", "Owner"),
}


def make_intake_officer_headers(user_id: str = "intake-1") -> dict:
    return build_user_headers(user_id, "IntakeOfficer")


def make_epidemiologist_headers(user_id: str = "epi-1") -> dict:
    return build_user_headers(user_id, "Epidemiologist")


def make_veterinarian_headers(user_id: str = "vet-1") -> dict:
    return build_user_headers(user_id, "Veterinarian")


def make_animal_control_officer_headers(user_id: str = "aco-1") -> dict:
    return build_user_headers(user_id, "AnimalControlOfficer")


def make_health_dept_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "HealthDeptAdmin")


def make_owner_headers(owner_user_id: str) -> dict:
    """For the Owner role (entity_backed:Owner). Pass the acting Owner entity's id
    so the ownership check (citation.owner_id == X-User-ID) passes."""
    return build_user_headers(owner_user_id, "Owner")
