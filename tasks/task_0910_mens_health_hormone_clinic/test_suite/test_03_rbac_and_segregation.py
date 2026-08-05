"""Role-based access control denials and segregation of duties."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    create_patient_payload, create_pharmacist_payload, create_membership_plan_payload,
    create_prescription_payload, create_adverse_event_payload,
    make_patient_headers, make_pharmacist_headers,
    setup_active_plan,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_patient_cannot_issue_prescription_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 (endpoint table): POST `/clinic/prescriptions` is authorized for `Clinician`
    only.

    Design: Corner/rbac/patient_cannot_issue_prescription_forbidden
    """
    patient = validate_success(api.create_patient(create_patient_payload(), ADMIN), 201)
    payload = create_prescription_payload(NON_EXISTENT_UUID, patient["id"])
    validate_error(
        api.create_prescription(payload, make_patient_headers(patient["id"])),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403,
    )


def test_pharmacist_cannot_create_membership_plan_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 (endpoint table): POST `/clinic/membership-plans` is authorized for
    `ClinicAdmin` only.

    Design: Corner/rbac/pharmacist_cannot_create_membership_plan_forbidden
    """
    pharmacist = validate_success(api.create_pharmacist(create_pharmacist_payload(), ADMIN), 201)
    validate_error(
        api.create_membership_plan(
            create_membership_plan_payload(tier="CORE"), make_pharmacist_headers(pharmacist["id"])
        ),
        ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403,
    )


def test_triage_by_plan_owner_returns_segregation(api):
    """PRD §3.7: "the reviewing clinician's `X-User-ID` must differ from the implicated
    plan's `clinician_id`, or triage fails with `ERR_SEGREGATION_OF_DUTIES` — the
    safety reviewer may never be the plan's own prescriber."

    Design: Corner/rbac/adverse_triage_by_plan_owner_returns_segregation
    """
    ctx = setup_active_plan()
    event = get_success_data(
        api.create_adverse_event(
            create_adverse_event_payload(ctx["patient_id"], ctx["plan_id"], description="headache"),
            make_patient_headers(ctx["patient_id"]),
        )
    )
    # The plan's owning clinician attempts the triage -> segregation violation.
    validate_error(
        api.triage_adverse_event(event["id"], {"severity": "MILD"}, ctx["clinician_headers"]),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403,
    )
