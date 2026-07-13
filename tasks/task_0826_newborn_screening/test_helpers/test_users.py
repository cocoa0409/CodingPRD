"""Pre-built role headers for every role in the Newborn Screening PRD (§2.1).

Three roles are opaque operator identities (LabTechnician, FollowUpCoordinator,
ProgramAdmin). Two roles are entity_backed:
  - BirthFacilityUser  — X-User-ID is a Facility.id (ownership on infant's facility)
  - SpecialtyClinician — X-User-ID is a SpecialtyClinic.id (ownership on appointment's clinic)

For any ownership-gated call by an entity_backed role, mint per-instance headers by
passing the actual entity's id to the corresponding make_* function.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles, or entity_backed calls that do NOT exercise
# ownership (e.g. a 404-on-missing-resource, a 400-on-bad-payload).
TEST_USERS = {
    "lab_technician_headers": build_user_headers("test-labtech-1", "LabTechnician"),
    "follow_up_coordinator_headers": build_user_headers(
        "test-coordinator-1", "FollowUpCoordinator"
    ),
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    # Fallbacks — the make_* builders below are the correct choice when the
    # entity_backed role must own the resource under test.
    "birth_facility_user_headers": build_user_headers(
        "test-facility-fallback", "BirthFacilityUser"
    ),
    "specialty_clinician_headers": build_user_headers(
        "test-clinic-fallback", "SpecialtyClinician"
    ),
}


def make_program_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_lab_technician_headers(user_id: str = "test-labtech-1") -> dict:
    return build_user_headers(user_id, "LabTechnician")


def make_follow_up_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "FollowUpCoordinator")


def make_birth_facility_user_headers(user_id: str) -> dict:
    """For BirthFacilityUser (entity_backed:Facility). Pass the actual Facility.id as
    user_id whenever the call is ownership-gated (register infant, consent, collect
    specimen, point-of-care)."""
    return build_user_headers(user_id, "BirthFacilityUser")


def make_specialty_clinician_headers(user_id: str) -> dict:
    """For SpecialtyClinician (entity_backed:SpecialtyClinic). Pass the actual
    SpecialtyClinic.id as user_id whenever the call is ownership-gated (complete a
    confirmatory appointment)."""
    return build_user_headers(user_id, "SpecialtyClinician")
