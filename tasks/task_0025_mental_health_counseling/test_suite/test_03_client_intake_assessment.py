"""Client onboarding and the first-visit assessment gate (PRD §3.3)."""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    bring_counselor_to_active,
    create_appointment_in_hold,
    create_appointment_payload,
    create_client,
    create_client_payload,
    create_slot,
    confirm_appointment,
    DEFAULT_T0,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    shift,
    validate_error,
    validate_success,
)


class TestClientRegistration:
    def test_create_client_starts_pending_assessment(self, api, admin_headers):
        """PRD §3.3: "On registration `assessment_status` begins at `PENDING`,
        `package_balance_sessions` begins at zero, and `risk_flag` begins at
        `NONE`."
        """
        res = api.create_client(create_client_payload(), admin_headers)
        client = validate_success(res, expected_status=201)
        assert client["assessment_status"] == "PENDING"
        assert client["package_balance_sessions"] == 0
        assert client["risk_flag"] == "NONE"

    @pytest.mark.parametrize("bad_phone", [
        "1234567",            # missing +
        "+0123456789",        # starts with +0
        "+1",                 # too short
        "+12345",             # only 4 digits after +1
    ])
    def test_invalid_emergency_phone_format_rejected(self, api, admin_headers, bad_phone):
        """PRD §3.3: "The phone must match the E.164 pattern of a leading
        plus sign followed by a digit between 1 and 9 and then six to
        fourteen further digits."
        """
        payload = create_client_payload(emergency_contact_phone=bad_phone)
        res = api.create_client(payload, admin_headers)
        # PRD §2.6 says generic field-level validation -> ERR_VALIDATION 422.
        validate_error(res, "ERR_VALIDATION", expected_status=422)


class TestAssessmentGate:
    def test_pending_client_cannot_book_standard(self, api):
        """PRD §3.3: "Until the client has completed an `INTAKE` appointment,
        every other `appointment_type` is rejected: a client whose
        `assessment_status` is `PENDING` and who attempts to book a
        `STANDARD` or `FOLLOW_UP` appointment is rejected with
        `ERR_INTAKE_REQUIRED`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()                  # assessment_status = PENDING
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=slot["id"],
            appointment_type="STANDARD",
            payment_mode="PAY_PER_SESSION",
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        validate_error(res, "ERR_INTAKE_REQUIRED", expected_status=422)

    def test_pending_client_cannot_book_follow_up(self, api):
        """PRD §3.3: "a client whose `assessment_status` is `PENDING` and who
        attempts to book a `STANDARD` or `FOLLOW_UP` appointment is rejected
        with `ERR_INTAKE_REQUIRED`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=slot["id"],
            appointment_type="FOLLOW_UP",
            payment_mode="PAY_PER_SESSION",
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        validate_error(res, "ERR_INTAKE_REQUIRED", expected_status=422)

    def test_pending_client_can_book_intake(self, api):
        """PRD §3.4: "either the client's `assessment_status` must be
        `COMPLETED` or the chosen `appointment_type` must be `INTAKE`".
        Intake booking should succeed for a PENDING client.
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=slot["id"],
            appointment_type="INTAKE",
            payment_mode="PAY_PER_SESSION",
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        appt = validate_success(res, expected_status=201)
        assert appt["appointment_type"] == "INTAKE"
        assert appt["status"] == "HOLD"

    def test_in_progress_client_cannot_book_second_intake(self, api):
        """PRD §3.3: "a client whose `assessment_status` is `IN_PROGRESS`
        (meaning their intake appointment is confirmed but not yet
        completed) may not book a second `INTAKE` — the request is rejected
        with `ERR_INTAKE_ALREADY_IN_PROGRESS`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        # First intake booking and confirm — should flip assessment_status
        # PENDING -> IN_PROGRESS per PRD §3.4.
        intake_slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        intake_appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=intake_slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        confirm_appointment(client, intake_appt)
        # Second intake booking should be rejected.
        slot2 = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=300))
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=slot2["id"],
            appointment_type="INTAKE",
            payment_mode="PAY_PER_SESSION",
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        validate_error(res, "ERR_INTAKE_ALREADY_IN_PROGRESS", expected_status=422)


class TestPackageCredit:
    def test_admin_credits_package_balance(self, api, admin_headers):
        """PRD §3.3: "A `PlatformAdmin` may also credit prepaid sessions to
        the client's package by submitting a payload with `sessions` and
        `version`; this increments `package_balance_sessions` by the
        supplied count."
        """
        client = create_client()
        res = api.credit_package(
            client["id"], {"sessions": 5, "version": client["version"]},
            admin_headers,
        )
        updated = validate_success(res, expected_status=200)
        assert updated["package_balance_sessions"] == 5
