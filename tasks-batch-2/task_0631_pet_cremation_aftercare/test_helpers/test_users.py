"""Pre-built role headers for every role in the PRD (§2.1).

Two identity families:
  - CrematoryAdmin and CrematoryOperator: identity is opaque. X-User-ID is an operator
    identifier never compared to any entity id, so the shared constants are canonical.
  - ClinicStaff and PetOwner: entity-backed. X-User-ID must be the acting Clinic.id or
    PetOwner.id for ownership-gated calls; use the per-instance builders for those.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque crematory roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "CrematoryAdmin"),
    "operator_headers": build_user_headers("test-operator-1", "CrematoryOperator"),
    # Entity-backed roles — shared constants are fallbacks for non-ownership tests only
    # (e.g. 401/403/404 checks that never reach an ownership comparison).
    "clinic_staff_headers": build_user_headers("test-clinic-1", "ClinicStaff"),
    "pet_owner_headers": build_user_headers("test-owner-1", "PetOwner"),
}


def make_clinic_staff_headers(clinic_id: str) -> dict:
    """For ClinicStaff (entity_backed:Clinic). Pass the actual Clinic.id whenever the
    call is ownership-gated to the clinic."""
    return build_user_headers(clinic_id, "ClinicStaff")


def make_pet_owner_headers(owner_id: str) -> dict:
    """For PetOwner (entity_backed:PetOwner). Pass the actual PetOwner.id whenever the
    call is ownership-gated to the owner (e.g. paying an owner-billed invoice)."""
    return build_user_headers(owner_id, "PetOwner")
