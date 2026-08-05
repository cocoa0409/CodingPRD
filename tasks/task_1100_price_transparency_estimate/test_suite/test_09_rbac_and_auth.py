"""Authentication, role authorization, and patient ownership scoping."""
from test_helpers import (
    validate_error, ApiErrorId, create_procedure_payload,
    fixtures, make_patient_headers, TEST_USERS,
)

PROVIDER = TEST_USERS["provider_staff_headers"]


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a role string the
    system does not recognize, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/unauthenticated_missing_headers_returns_401
    """
    resp = api.create_procedure(create_procedure_payload(), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_patient_cannot_create_procedure(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED." Section 4 authorizes only ProviderStaff for POST /procedures.

    Design: Corner/rbac/patient_cannot_create_procedure
    """
    plan = fixtures.new_benefit_plan(api)
    patient = fixtures.new_patient(api, plan["id"])
    resp = api.create_procedure(create_procedure_payload(),
                                make_patient_headers(patient["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_patient_cannot_accept_other_patients_estimate(api):
    """PRD §2.1: "A PatientUser mutation that targets a resource tied to a
    different patient is rejected with ERR_UNAUTHORIZED." PRD §3.5: "A PatientUser
    who does not own the patient is refused with ERR_UNAUTHORIZED."

    Design: Corner/rbac/patient_cannot_accept_other_patients_estimate
    """
    b = fixtures.setup_insured_issued_single_line(api)
    patient_b = fixtures.new_patient(api, b["plan"]["id"])
    resp = api.accept_estimate(b["estimate"]["id"], make_patient_headers(patient_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
