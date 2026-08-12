"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ProgramAdministrator, CaseWorker, AppealsOfficer,
PharmacyDispenser) may share a constant. Entity-backed roles (Patient,
Prescriber) MUST be built per instance with the real entity id whenever the
call is ownership-gated, so `make_patient_headers` / `make_prescriber_headers`
are the canonical entry points for those.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "program_admin_headers": build_user_headers("pa_1", "ProgramAdministrator"),
    "case_worker_headers": build_user_headers("cw_1", "CaseWorker"),
    "case_worker_2_headers": build_user_headers("cw_2", "CaseWorker"),
    "appeals_officer_headers": build_user_headers("ao_1", "AppealsOfficer"),
    "dispenser_headers": build_user_headers("pd_1", "PharmacyDispenser"),
    # Fallbacks for non-ownership calls only; never use these for
    # ownership-gated Patient/Prescriber operations.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "prescriber_headers": build_user_headers("test-prescriber-1", "Prescriber"),
}


def make_patient_headers(patient_id: str) -> dict:
    """Patient is entity-backed: X-User-ID must equal the Patient.id whenever
    the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(patient_id, "Patient")


def make_prescriber_headers(prescriber_id: str) -> dict:
    """Prescriber is entity-backed: X-User-ID must equal the Prescriber.id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(prescriber_id, "Prescriber")


def make_case_worker_headers(user_id: str) -> dict:
    """CaseWorker is opaque, but reviewer identity is recorded; use a distinct
    user id per logical caseworker."""
    return build_user_headers(user_id, "CaseWorker")


def make_appeals_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AppealsOfficer")
