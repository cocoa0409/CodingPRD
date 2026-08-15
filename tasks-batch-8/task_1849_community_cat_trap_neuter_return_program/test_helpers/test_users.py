"""Pre-built role headers for every role in the PRD (§2.1).

Caretaker and FosterVolunteer are entity-backed roles: X-User-ID must be the id
of the acting Caretaker record or the acting FosterHome record. The shared
constants below are safe only for calls that do not exercise ownership; any
ownership-gated call MUST use make_caretaker_headers / make_volunteer_headers
with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: X-User-ID is not tied to any persisted entity.
    "coordinator_headers": build_user_headers("test-coordinator-1", "ProgramCoordinator"),
    "clinic_staff_headers": build_user_headers("test-clinic-staff-1", "ClinicStaff"),
    "officer_headers": build_user_headers("test-officer-1", "AnimalControlOfficer"),
    # Entity-backed roles: fallback only for tests that never touch ownership.
    "caretaker_headers": build_user_headers("test-caretaker-1", "Caretaker"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "FosterVolunteer"),
}


def make_caretaker_headers(caretaker_id: str) -> dict:
    """For Caretaker (entity-backed). Pass the actual Caretaker.id whenever the
    call is ownership-gated (booking, mark-trapped, cancel, voucher commit)."""
    return build_user_headers(caretaker_id, "Caretaker")


def make_volunteer_headers(foster_home_id: str) -> dict:
    """For FosterVolunteer (entity-backed: the FosterHome id). Pass the actual
    FosterHome.id whenever the call is ownership-gated (graduate, return)."""
    return build_user_headers(foster_home_id, "FosterVolunteer")


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    """For ProgramCoordinator (opaque): user_id is any operator identifier."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_clinic_staff_headers(user_id: str = "test-clinic-staff-1") -> dict:
    """For ClinicStaff (opaque)."""
    return build_user_headers(user_id, "ClinicStaff")


def make_officer_headers(user_id: str = "test-officer-1") -> dict:
    """For AnimalControlOfficer (opaque)."""
    return build_user_headers(user_id, "AnimalControlOfficer")
