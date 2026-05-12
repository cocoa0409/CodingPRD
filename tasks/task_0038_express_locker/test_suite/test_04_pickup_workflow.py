"""Pickup workflow — initiate, code auth, cancel-pickup, confirm. PRD §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CompartmentStatus,
    OvertimeFeePaymentStatus,
    OvertimeFeeVariant,
    ParcelStatus,
    advance_clock,
    advance_hours,
    confirm_deposit,
    deposit_parcel,
    get_compartment,
    get_fee_records,
    get_parcel,
    initiate_pickup,
    initiate_pickup_payload,
    latest_provisional_fee,
    make_recipient_headers,
    pay_fee_record,
    pickup_confirm,
    setup_basic_scenario,
    setup_deposited_parcel,
    setup_pickup_pending_parcel,
    setup_picked_up_parcel,
    validate_error,
    validate_success,
)


class TestInitiatePickupCodeAuth:
    """PRD §3.4: 'a code entered against a parcel whose code is wrong is
    rejected with ERR_INVALID_PICKUP_CODE.'"""

    def test_initiate_pickup_with_wrong_code_rejected(self, api):
        """PRD §3.4: 'a code entered against a parcel whose code is wrong
        is rejected with ERR_INVALID_PICKUP_CODE.'

        Claim: POST /initiate-pickup with method=CODE and a bogus code
        returns ERR_INVALID_PICKUP_CODE.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.initiate_pickup(
            parcel["id"],
            initiate_pickup_payload(method="CODE", code="000000"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PICKUP_CODE.value)
        # Parcel must remain in DEPOSITED — the bad code did not advance state.
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.DEPOSITED.value

    def test_initiate_pickup_with_valid_code_advances_to_pickup_pending(
        self, api,
    ):
        """PRD §3.4: 'The first successful attempt advances the parcel
        from DEPOSITED to PICKUP_PENDING, freezes the provisional overtime
        fee onto the parcel as provisional_overtime_fee, and materialises
        an OvertimeFeeRecord with variant = PROVISIONAL.'

        Claim: a valid CODE call advances status to PICKUP_PENDING and
        creates a PROVISIONAL OvertimeFeeRecord.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        # No clock advance — provisional fee will be 0 inside FREE_HOURS.
        result = initiate_pickup(parcel, method="CODE")
        assert result["status"] == ParcelStatus.PICKUP_PENDING.value
        fees = get_fee_records(parcel["id"])
        prov = [f for f in fees if f.get("variant") ==
                OvertimeFeeVariant.PROVISIONAL.value]
        assert len(prov) >= 1, (
            "PRD §3.4 requires a PROVISIONAL OvertimeFeeRecord "
            "after first successful pickup."
        )


class TestPickupPendingHold:
    """PRD §3.4: 'PICKUP_PENDING is a hold state … the same revert occurs
    on an explicit cancel.'"""

    def test_cancel_pickup_reverts_to_deposited(self, api):
        """PRD §3.4: 'A recipient who began a pickup but does not wish to
        continue may cancel the in-flight PICKUP_PENDING, which reverts
        the parcel to DEPOSITED and leaves the provisional fee record
        UNPAID for audit.'

        Claim: POST /cancel-pickup reverts status to DEPOSITED while the
        PROVISIONAL fee record stays UNPAID.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.cancel_pickup(parcel["id"], headers)
        validate_success(resp)
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.DEPOSITED.value
        fees = get_fee_records(parcel["id"])
        prov = [f for f in fees if f.get("variant") ==
                OvertimeFeeVariant.PROVISIONAL.value]
        assert prov, "PROVISIONAL fee record must persist for audit."
        assert any(
            f["payment_status"] == OvertimeFeePaymentStatus.UNPAID.value
            for f in prov
        ), "PRD §3.4: 'the provisional fee record retained UNPAID'."


class TestPickupConfirm:
    """PRD §3.4: pickup-confirm is the only transition to PICKED_UP."""

    def test_pickup_confirm_with_unpaid_fee_blocked(self, api):
        """PRD §3.4: 'If the parcel's provisional_overtime_fee is greater
        than zero and fee_waived is false, the latest OvertimeFeeRecord
        of variant = PROVISIONAL must already be in payment_status =
        PAID; otherwise the confirm is rejected with
        ERR_FEE_PAYMENT_REQUIRED (HTTP 402).'

        Claim: a pickup-confirm with provisional fee > 0 and UNPAID is
        rejected with ERR_FEE_PAYMENT_REQUIRED at HTTP 402.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,  # 1 hour past free → 100c provisional fee
        )
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.pickup_confirm(parcel["id"], headers)
        validate_error(resp, ApiErrorId.ERR_FEE_PAYMENT_REQUIRED.value)

    def test_pickup_confirm_after_payment_completes_pickup(self, api):
        """PRD §3.4: 'If the gate passes, the parcel advances from
        PICKUP_PENDING to PICKED_UP, picked_up_at is set to the current
        instant, the compartment is released from OCCUPIED to AVAILABLE
        and its current_parcel_id cleared.'

        Claim: after paying the provisional fee, pickup-confirm advances
        status to PICKED_UP, releases the compartment, and sets picked_up_at.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None and prov.get("amount_cents", 0) > 0
        pay_fee_record(prov["id"])
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.pickup_confirm(parcel["id"], headers)
        data = validate_success(resp)
        assert data["status"] == ParcelStatus.PICKED_UP.value
        assert data.get("picked_up_at") is not None
        comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert comp["status"] == CompartmentStatus.AVAILABLE.value
        assert comp.get("current_parcel_id") in (None, "")

    def test_pickup_confirm_with_zero_fee_completes_directly(self, api):
        """PRD §3.4: 'When the parcel was waived (for example because the
        deposit was a wrong-deposit by the courier or the machine had
        been in SYSTEM_FAULT), the fee gate is bypassed.'

        Companion claim — with provisional fee zero (within FREE_HOURS),
        pickup-confirm passes directly because PRD §3.4 makes the fee
        gate conditional on 'provisional_overtime_fee is greater than
        zero'. Within free 24h, that gate cannot fire.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=0,
        )
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.pickup_confirm(parcel["id"], headers)
        data = validate_success(resp)
        assert data["status"] == ParcelStatus.PICKED_UP.value


class TestPickupOnPickedUpParcel:
    """PRD §3.4: terminal-state checks via PRD §2.9 priority 5."""

    def test_initiate_pickup_on_picked_up_parcel_rejected(self, api):
        """PRD §3.3 / §3.4 / §2.9: state precondition guard
        (ERR_PARCEL_STATE_CHANGED).

        Claim: /initiate-pickup on a parcel whose status is already
        PICKED_UP returns ERR_PARCEL_STATE_CHANGED.
        """
        machine, courier, parcel = setup_picked_up_parcel(
            elapsed_hours_before_pickup=0,
        )
        headers = make_recipient_headers(parcel["recipient_phone"])
        resp = api.initiate_pickup(
            parcel["id"],
            initiate_pickup_payload(method="CODE", code="000000"),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_PARCEL_STATE_CHANGED.value)
