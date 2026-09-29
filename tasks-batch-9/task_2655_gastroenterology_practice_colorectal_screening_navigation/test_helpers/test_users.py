"""Pre-built role headers for every role named in the PRD (§2.1).

Six of the eight roles are operational rather than personal: their `X-User-ID`
is an opaque operator identifier that is never compared to any entity's `id`,
so a shared constant is the canonical form for them.

The remaining two roles are entity-backed. `Endoscopist` carries the acting
`Clinician.id` and `Patient` carries the acting `Patient.id`, so ownership-gated
calls MUST use the per-instance builders below with the real entity id.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the six opaque roles, and for entity-backed roles
# only in calls that exercise no ownership check.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "practice_admin_headers": build_user_headers("op-practice-admin-1", "PracticeAdmin"),
    "referral_coordinator_headers": build_user_headers(
        "op-referral-coordinator-1", "ReferralCoordinator"
    ),
    "patient_navigator_headers": build_user_headers(
        "op-patient-navigator-1", "PatientNavigator"
    ),
    "pathologist_headers": build_user_headers("op-pathologist-1", "Pathologist"),
    "billing_specialist_headers": build_user_headers(
        "op-billing-specialist-1", "BillingSpecialist"
    ),
    "quality_officer_headers": build_user_headers("op-quality-officer-1", "QualityOfficer"),
    # Entity-backed roles: fallback only for non-ownership calls.
    "endoscopist_headers": build_user_headers("op-endoscopist-1", "Endoscopist"),
    "patient_headers": build_user_headers("op-patient-1", "Patient"),
}


def make_endoscopist_headers(clinician_id: str) -> Dict[str, str]:
    """Headers for the `Endoscopist` role. `X-User-ID` is the acting Clinician's id;
    pass the real Clinician id whenever the call is ownership-gated (starting,
    completing or aborting a procedure, or attesting an override)."""
    return build_user_headers(clinician_id, "Endoscopist")


def make_patient_headers(patient_id: str) -> Dict[str, str]:
    """Headers for the `Patient` role. `X-User-ID` is the acting Patient's id;
    pass the real Patient id whenever the call is ownership-gated (reading one
    patient row, reading one episode, or submitting a prep attestation)."""
    return build_user_headers(patient_id, "Patient")


def make_quality_officer_headers(user_id: str) -> Dict[str, str]:
    """Headers for the `QualityOfficer` role with an explicit opaque operator id,
    used when a test needs to assert the id recorded in `attesting_user_id`."""
    return build_user_headers(user_id, "QualityOfficer")


# Convenience aliases used throughout the suite.
PRACTICE_ADMIN = TEST_USERS["practice_admin_headers"]
REFERRAL_COORDINATOR = TEST_USERS["referral_coordinator_headers"]
PATIENT_NAVIGATOR = TEST_USERS["patient_navigator_headers"]
PATHOLOGIST = TEST_USERS["pathologist_headers"]
BILLING_SPECIALIST = TEST_USERS["billing_specialist_headers"]
QUALITY_OFFICER = TEST_USERS["quality_officer_headers"]
