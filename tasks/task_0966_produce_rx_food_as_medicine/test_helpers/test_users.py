"""Pre-built role headers for every role in the PRD (§2.1).

Entity-backed roles (FunderAnalyst -> Funder, ClinicStaff -> Clinic,
Participant -> Patient, RetailerStaff -> Retailer) compare X-User-ID against a
real entity's id on ownership-gated calls; use the per-instance builders for
those. The shared constants are safe only for opaque roles or for tests whose
outcome does not depend on ownership (400/404 probes, wrong-role checks).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "educator_headers": build_user_headers("test-educator-1", "Educator"),
    # Entity-backed roles: fallback constants for NON-ownership tests only.
    "funder_analyst_headers": build_user_headers("test-funder-analyst-1", "FunderAnalyst"),
    "clinic_staff_headers": build_user_headers("test-clinic-staff-1", "ClinicStaff"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
    "retailer_staff_headers": build_user_headers("test-retailer-staff-1", "RetailerStaff"),
}


def make_funder_analyst_headers(user_id: str) -> dict:
    """FunderAnalyst is entity-backed by Funder: pass the real Funder.id
    whenever the call is ownership-gated (fund / accept / return)."""
    return build_user_headers(user_id, "FunderAnalyst")


def make_clinic_staff_headers(user_id: str) -> dict:
    """ClinicStaff is entity-backed by Clinic: pass the real Clinic.id
    whenever the call is ownership-gated (patients, referrals, renewals,
    biometric readings)."""
    return build_user_headers(user_id, "ClinicStaff")


def make_participant_headers(user_id: str) -> dict:
    """Participant is entity-backed by Patient: pass the real Patient.id."""
    return build_user_headers(user_id, "Participant")


def make_retailer_staff_headers(user_id: str) -> dict:
    """RetailerStaff is entity-backed by Retailer: pass the real Retailer.id
    whenever the call is ownership-gated (redemption create/void)."""
    return build_user_headers(user_id, "RetailerStaff")
