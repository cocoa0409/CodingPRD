"""Pre-built role headers for every role in the PRD (PRD 2.1).

Four roles (ClinicAdmin, Nurse, Embryologist, BillingSpecialist) are operator
roles whose X-User-ID is opaque — the shared constant form is canonical for them.
The Patient role is entity-backed: a patient's X-User-ID must equal the acting
Patient's id for ownership-gated calls (sign/revoke own consent). For those
calls always use make_patient_headers(patient_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque operator roles — shared constant is the canonical form
    "clinic_admin_headers": build_user_headers("test-admin-1", "ClinicAdmin"),
    "nurse_headers": build_user_headers("test-nurse-1", "Nurse"),
    "embryologist_headers": build_user_headers("test-embryologist-1", "Embryologist"),
    "billing_specialist_headers": build_user_headers("test-billing-1", "BillingSpecialist"),
    # entity_backed Patient — shared constant is a fallback for NON-ownership tests
    # only (e.g. reading a 404 resource). Ownership-gated calls must use the builder.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
}


def make_patient_headers(patient_id: str) -> dict:
    """Headers for the Patient role (entity_backed:Patient).

    Pass the actual Patient.id as user_id whenever the call is ownership-gated:
    signing a consent (patient_id must equal X-User-ID) or revoking own consent.
    """
    return build_user_headers(patient_id, "Patient")
