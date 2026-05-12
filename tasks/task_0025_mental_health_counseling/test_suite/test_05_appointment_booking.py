"""Appointment booking flow: HOLD creation, confirm, hold expiry (PRD §3.4)."""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    assert_appointment,
    bring_counselor_to_active,
    confirm_appointment,
    create_appointment_in_hold,
    create_appointment_payload,
    create_client,
    create_slot,
    credit_client_package,
    DEFAULT_T0,
    get_appointment,
    list_settlement_ledger_for_appointment,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    setup_counselor_and_completed_client,
    shift,
    sweep_holds,
    validate_error,
    validate_success,
)


class TestBookingHoldFlow:
    def test_create_appointment_puts_slot_in_held(self, api):
        """PRD §3.4: "On success the slot transitions to `HELD` with
        `held_until` set to current time plus fifteen minutes and
        `held_appointment_id` set to the new appointment's `id`, the
        appointment is persisted in `HOLD` with `channel` mirrored from the
        slot, and the response carries the new appointment."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200),
                           channel="VIDEO")
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE",
        )
        assert_appointment(appt)
        assert appt["status"] == "HOLD"
        assert appt["channel"] == "VIDEO"
        # Re-fetch the slot to see its HELD state.
        from test_helpers import api_client as ac
        slot_after = ac.list_availability_slots(
            make_counselor_headers(counselor["id"]),
            params={"counselor_id": counselor["id"]},
        ).json()["data"]
        held = [s for s in slot_after if s["id"] == slot["id"]][0]
        assert held["status"] == "HELD"
        assert held["held_appointment_id"] == appt["id"]


class TestBookingTooLate:
    def test_booking_within_one_hour_rejected(self, api):
        """PRD §3.4: "the current time must be strictly less than `start_at`
        minus one hour (otherwise `ERR_BOOKING_TOO_LATE`)..."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        # Slot 30 minutes from now.
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        # Advance clock so that now() is INSIDE the one-hour buffer.
        advance_clock(shift(DEFAULT_T0, hours=199, minutes=45))
        payload = create_appointment_payload(
            counselor_id=counselor["id"],
            client_id=client["id"],
            slot_id=slot["id"],
            appointment_type="INTAKE",
            payment_mode="PAY_PER_SESSION",
        )
        res = api.create_appointment(payload, make_client_headers(client["id"]))
        validate_error(res, "ERR_BOOKING_TOO_LATE", expected_status=422)


class TestConfirm:
    def test_confirm_pps_writes_charge_row(self, api):
        """PRD §3.4: "On confirmation, `confirmed_at` is set to current time,
        the slot becomes `BOOKED`, a CHARGE row is written to
        `SettlementLedger`..."
        """
        counselor, client = setup_counselor_and_completed_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_at"] is not None
        rows = list_settlement_ledger_for_appointment(confirmed["id"])
        assert any(r["direction"] == "CHARGE" for r in rows), \
            "PRD §3.4 + §3.8: confirm writes a CHARGE row to SettlementLedger"

    def test_confirm_package_decrements_balance(self, api):
        """PRD §3.4: "if the payment mode is `PACKAGE` the client's
        `package_balance_sessions` is decremented by one."
        """
        counselor, client = setup_counselor_and_completed_client(
            package_balance_sessions=3,
        )
        balance_before = client["package_balance_sessions"]
        assert balance_before == 3
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PACKAGE",
        )
        confirm_appointment(client, appt)
        from test_helpers import get_client
        client_after = get_client(client["id"])
        assert client_after["package_balance_sessions"] == balance_before - 1, \
            "PRD §3.4: PACKAGE confirm decrements package_balance_sessions by 1"

    def test_confirm_package_with_zero_balance_rejected(self, api):
        """PRD §3.4: "for `PACKAGE` the client's `package_balance_sessions`
        must be at least 1 (otherwise `ERR_INSUFFICIENT_PACKAGE_BALANCE`)."
        """
        counselor, client = setup_counselor_and_completed_client(
            package_balance_sessions=0,
        )
        assert client["package_balance_sessions"] == 0
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=400))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="STANDARD", payment_mode="PACKAGE",
        )
        res = api.confirm_appointment(
            appt["id"], make_client_headers(client["id"]),
        )
        validate_error(res, "ERR_INSUFFICIENT_PACKAGE_BALANCE", expected_status=422)

    def test_confirm_intake_flips_assessment_in_progress(self, api):
        """PRD §3.4: "When the appointment is an `INTAKE` and the client's
        `assessment_status` was `PENDING` at confirmation, the same
        operation flips `assessment_status` to `IN_PROGRESS`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        assert client["assessment_status"] == "PENDING"
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        confirm_appointment(client, appt)
        from test_helpers import get_client
        client_after = get_client(client["id"])
        assert client_after["assessment_status"] == "IN_PROGRESS"


class TestHoldExpiry:
    def test_hold_expiry_sweep_releases_slot(self):
        """PRD §3.4: "If the hold expires before confirmation, a periodic
        hold-expiry sweep runs across all `HELD` slots whose `held_until`
        has elapsed, transitioning the slot from `HELD` back to `OPEN` and
        the appointment from `HOLD` to `CANCELLED` with
        `cancellation_reason` set to `NO_SHOW_AUTO`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = create_client()
        slot = create_slot(counselor=counselor, start_at=shift(DEFAULT_T0, hours=200))
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        # held_until = now + 15m. Advance 16m past current clock.
        advance_clock(shift(DEFAULT_T0, minutes=16))
        sweep_holds()
        appt_after = get_appointment(appt["id"])
        assert appt_after["status"] == "CANCELLED"
        assert appt_after["cancellation_reason"] == "NO_SHOW_AUTO"
