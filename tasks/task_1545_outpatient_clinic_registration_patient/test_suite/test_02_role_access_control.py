"""Role-based access control and operator-header authentication (PRD §2.1)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_patient_payload,
    create_payment_payload,
    get_success_data,
    schedule_appointment,
    validate_error,
)

REG = TEST_USERS["registrar_headers"]
FC = TEST_USERS["financial_counselor_headers"]
FD = TEST_USERS["front_desk_headers"]


def test_front_desk_cannot_create_patients(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted on
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /patient-access/patients is authorized for Registrar only.

    Design: Corner/rbac/front_desk_cannot_create_patients
    """
    res = api.create_patient(
        create_patient_payload(
            first_name="No",
            last_name="Perm",
            date_of_birth="1990-01-01",
            sex_at_birth="M",
            primary_phone="+15551500001",
        ),
        FD,
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_registrar_cannot_post_payments(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted on
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /patient-access/appointments/{id}/payments is authorized for
    FinancialCounselor only.

    Design: Corner/rbac/registrar_cannot_post_payments
    """
    patient = get_success_data(
        api.create_patient(
            create_patient_payload(
                first_name="So",
                last_name="D",
                date_of_birth="1991-02-02",
                sex_at_birth="F",
                primary_phone="+15551500002",
            ),
            REG,
        )
    )
    appt = schedule_appointment(
        patient["id"], scheduled_start="2026-09-15T09:00:00Z", provider_code="DRSO"
    )
    res = api.create_payment(
        appt["id"], create_payment_payload(amount_cents=100, method="CASH", kind="POST"), REG
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request whose headers are missing, or whose `X-User-Role`
    is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    res = api.list_patients(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_financial_counselor_cannot_void_payment(api):
    """PRD §2.1: "A request whose role is authenticated but not permitted on
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: POST /patient-access/payments/{id}/void is authorized for
    AccessSupervisor only.

    Design: Corner/rbac/financial_counselor_cannot_void_payment
    """
    patient = get_success_data(
        api.create_patient(
            create_patient_payload(
                first_name="Void",
                last_name="Deny",
                date_of_birth="1992-03-03",
                sex_at_birth="M",
                primary_phone="+15551500003",
            ),
            REG,
        )
    )
    appt = schedule_appointment(
        patient["id"], scheduled_start="2026-09-16T09:00:00Z", provider_code="DRVD"
    )
    payment = get_success_data(
        api.create_payment(
            appt["id"], create_payment_payload(amount_cents=100, method="CASH", kind="POST"), FC
        )
    )
    res = api.void_payment(payment["id"], FC)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
