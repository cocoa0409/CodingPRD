"""Role-based access control.

Corner queue B: rbac section instances.
"""
from test_helpers import (
    create_patient,
    create_provider,
    validate_success,
    validate_error,
    ApiErrorId,
    make_clinician_headers,
    make_unknown_role_headers,
    TEST_USERS,
)
from test_helpers import api_client

FD = TEST_USERS["front_desk_headers"]


def test_front_desk_cannot_create_insurance_plan():
    """PRD §2.1: "A `BillingSpecialist` owns insurance configuration, coverage
    attachment, predetermination, claims and their attachments, adjudication, and
    payment plans."
    PRD §2.1: "When the headers are present and well-formed but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    FrontDesk calling POST /insurance-plans (a BillingSpecialist operation) is
    rejected with ERR_FORBIDDEN.

    Design: Corner/rbac/front_desk_cannot_create_insurance_plan
    """
    resp = api_client.create_insurance_plan(
        {"carrier_name": "X", "annual_maximum_cents": 100_000, "deductible_cents": 5_000,
         "preventive_coinsurance_pct": 100, "basic_coinsurance_pct": 80,
         "major_coinsurance_pct": 50}, FD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_clinician_cannot_schedule_appointment():
    """PRD §2.1: "A `FrontDesk` user handles registration, operatory management,
    scheduling, recare recall, and the acceptance or cancellation of treatment
    plans."
    PRD §2.1: "When the headers are present and well-formed but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."

    A Clinician calling POST /appointments (a FrontDesk operation) is rejected with
    ERR_FORBIDDEN.

    Design: Corner/rbac/clinician_cannot_schedule_appointment
    """
    patient = create_patient()
    provider = create_provider(provider_type="DENTIST")
    operatory = validate_success(api_client.create_operatory({"room_name": "OP-RB"}, FD), expected_status=201)
    resp = api_client.create_appointment(
        {"patient_id": patient["id"], "provider_id": provider["id"], "operatory_id": operatory["id"],
         "appointment_type": "OPERATIVE", "start_at": "2026-03-20T09:00:00Z",
         "end_at": "2026-03-20T10:00:00Z"}, make_clinician_headers(provider["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_unknown_role_returns_unauthenticated():
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    A request whose X-User-Role is an unrecognized role returns
    ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api_client.list_patients(make_unknown_role_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
