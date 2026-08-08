"""Pre-built role headers for every role in the PRD.

`PlatformAdmin`, `BillingSpecialist` and `ClinicCoordinator` carry an opaque
operator identifier that is never compared to any entity id, so the shared
constants below are the canonical form for them.

`SleepPhysician`, `Dentist` and `LabTechnician` bind `X-User-ID` to the acting
`Provider.id`, and `Patient` binds it to the acting `Patient.id`.  Every call
made on behalf of one of those four roles MUST use the matching per-instance
builder with the real row id, otherwise every ownership and care-team check
rejects the request.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the three opaque roles, and for tests where the
# request never reaches an ownership check (bad payloads, unknown ids).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "billing_specialist_headers": build_user_headers(
        "test-billing-1", "BillingSpecialist"
    ),
    "clinic_coordinator_headers": build_user_headers(
        "test-coordinator-1", "ClinicCoordinator"
    ),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "sleep_physician_headers": build_user_headers("test-physician-1", "SleepPhysician"),
    "dentist_headers": build_user_headers("test-dentist-1", "Dentist"),
    "lab_technician_headers": build_user_headers("test-lab-1", "LabTechnician"),
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_sleep_physician_headers(provider_id: str) -> dict:
    """For SleepPhysician; pass the acting Provider.id."""
    return build_user_headers(provider_id, "SleepPhysician")


def make_dentist_headers(provider_id: str) -> dict:
    """For Dentist; pass the acting Provider.id."""
    return build_user_headers(provider_id, "Dentist")


def make_lab_technician_headers(provider_id: str) -> dict:
    """For LabTechnician; pass the acting Provider.id."""
    return build_user_headers(provider_id, "LabTechnician")


def make_patient_headers(patient_id: str) -> dict:
    """For Patient; pass the acting Patient.id."""
    return build_user_headers(patient_id, "Patient")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_billing_specialist_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingSpecialist")


def make_clinic_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "ClinicCoordinator")


def no_auth_headers() -> dict:
    """Neither X-User-ID nor X-User-Role — the rung-1 probe."""
    return {"Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "test-someone-1") -> dict:
    """A well-formed pair whose role is not one of the seven declared names."""
    return build_user_headers(user_id, "Chiropractor")
