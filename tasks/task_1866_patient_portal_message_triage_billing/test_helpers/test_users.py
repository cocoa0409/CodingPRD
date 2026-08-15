"""Pre-built role headers for every role in the PRD (§2.1).

PracticeAdmin is an opaque operator identity: X-User-ID is not tied to any
persisted entity. The other five roles are entity-backed: Patient callers use
the acting Patient's id; TriageNurse/FrontDesk/Provider/BillingSpecialist
callers use the acting StaffMember's id. Ownership-gated calls MUST use the
per-instance builders below with the real entity id — never the shared
constants.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque role, and for tests that do not
# exercise ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role
# checks where the entity-backed id is never compared to a resource).
TEST_USERS = {
    "practice_admin_headers": build_user_headers("test-admin-1", "PracticeAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "triage_nurse_headers": build_user_headers("test-nurse-1", "TriageNurse"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "provider_headers": build_user_headers("test-provider-1", "Provider"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
}


def make_practice_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PracticeAdmin")


def make_patient_headers(patient_id: str) -> dict:
    """For Patient (entity_backed:Patient). Pass the acting Patient.id whenever
    the call is ownership-gated."""
    return build_user_headers(patient_id, "Patient")


def make_triage_nurse_headers(staff_id: str) -> dict:
    """For TriageNurse (entity_backed:StaffMember, staff_type NURSE). Pass the
    acting StaffMember.id whenever the call is ownership- or identity-gated."""
    return build_user_headers(staff_id, "TriageNurse")


def make_front_desk_headers(staff_id: str) -> dict:
    """For FrontDesk (entity_backed:StaffMember, staff_type FRONT_DESK)."""
    return build_user_headers(staff_id, "FrontDesk")


def make_provider_headers(staff_id: str) -> dict:
    """For Provider (entity_backed:StaffMember, staff_type PROVIDER)."""
    return build_user_headers(staff_id, "Provider")


def make_billing_specialist_headers(staff_id: str) -> dict:
    """For BillingSpecialist (entity_backed:StaffMember, staff_type
    BILLING_SPECIALIST)."""
    return build_user_headers(staff_id, "BillingSpecialist")
