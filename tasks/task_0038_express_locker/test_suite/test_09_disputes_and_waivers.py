"""Disputes lifecycle + manual waivers — PRD §3.8, §3.9."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DisputeStatus,
    FeeWaiverReason,
    OvertimeFeePaymentStatus,
    advance_clock,
    advance_hours,
    deposit_parcel,
    get_parcel,
    initiate_pickup,
    latest_provisional_fee,
    make_courier_headers,
    make_recipient_headers,
    open_dispute_payload,
    pay_fee_record,
    resolve_dispute_payload,
    setup_basic_scenario,
    setup_deposited_parcel,
    setup_pickup_pending_parcel,
    validate_error,
    validate_success,
    waive_fee_payload,
)


class TestOpenDispute:
    """PRD §3.9: 'A dispute may be opened by either the Recipient or the
    original Courier. … the system records the opener under
    opened_by_role (one of Recipient or Courier) and starts the dispute
    in status = OPEN.'"""

    def test_courier_opens_dispute_starts_open(self, api):
        """PRD §3.9: 'the system records the opener under opened_by_role
        (one of Recipient or Courier) and starts the dispute in status =
        OPEN.'

        Claim: POST /parcels/{id}/disputes by the courier yields a
        Dispute with status=OPEN and opened_by_role=Courier.
        """
        machine, _, courier, parcel = setup_deposited_parcel()
        resp = api.open_dispute(
            parcel["id"],
            open_dispute_payload(claim_type="DAMAGED"),
            make_courier_headers(courier["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == DisputeStatus.OPEN.value
        assert data["opened_by_role"] == "Courier"


class TestResolveDisputeOnceOnly:
    """PRD §3.9: 'A dispute that has already left OPEN cannot be resolved
    again — a second resolve call is rejected with
    ERR_DISPUTE_ALREADY_RESOLVED.'"""

    def test_second_resolve_rejected(
        self, api, operations_admin_headers,
    ):
        """PRD §3.9: 'A dispute that has already left OPEN cannot be
        resolved again — a second resolve call is rejected with
        ERR_DISPUTE_ALREADY_RESOLVED.'

        Claim: a second POST /disputes/{id}/resolve returns
        ERR_DISPUTE_ALREADY_RESOLVED.
        """
        machine, _, courier, parcel = setup_deposited_parcel()
        opened = validate_success(api.open_dispute(
            parcel["id"], open_dispute_payload(claim_type="DAMAGED"),
            make_courier_headers(courier["id"]),
        ), expected_status=201)
        api.resolve_dispute(
            opened["id"], resolve_dispute_payload(resolution="REJECT"),
            operations_admin_headers,
        )
        resp = api.resolve_dispute(
            opened["id"], resolve_dispute_payload(resolution="REJECT"),
            operations_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_ALREADY_RESOLVED.value)


class TestResolveWaiveOutcome:
    """PRD §3.9: 'WAIVE advances the dispute to RESOLVED_WAIVED, refunds
    the latest OvertimeFeeRecord if it was PAID (or marks it WAIVED if
    it was still UNPAID), sets Parcel.fee_waived to true with
    fee_waiver_reason = MANUAL_DISPUTE.'"""

    def test_waive_unpaid_marks_fee_waived_and_parcel_waived(
        self, api, operations_admin_headers,
    ):
        """PRD §3.9: 'WAIVE … (or marks it WAIVED if it was still UNPAID),
        sets Parcel.fee_waived to true with fee_waiver_reason =
        MANUAL_DISPUTE.'

        Claim: when the latest fee record is UNPAID at resolve time, a
        WAIVE resolution sets parcel.fee_waived=true with reason
        MANUAL_DISPUTE.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        # provisional fee unpaid
        opened = validate_success(api.open_dispute(
            parcel["id"], open_dispute_payload(claim_type="OVERTIME_DISPUTE"),
            make_recipient_headers(parcel["recipient_phone"]),
        ), expected_status=201)
        api.resolve_dispute(
            opened["id"],
            resolve_dispute_payload(resolution="WAIVE"),
            operations_admin_headers,
        )
        again = get_parcel(parcel["id"])
        assert again["fee_waived"] is True
        assert again["fee_waiver_reason"] == (
            FeeWaiverReason.MANUAL_DISPUTE.value
        )


class TestResolveRejectNoSideEffects:
    """PRD §3.9: 'REJECT advances the dispute to RESOLVED_REJECTED and
    produces no fee or courier side effects (outcome_amount_cents is 0).'"""

    def test_reject_resolution_outcome_zero(
        self, api, operations_admin_headers,
    ):
        """PRD §3.9: 'REJECT advances the dispute to RESOLVED_REJECTED
        and produces no fee or courier side effects
        (outcome_amount_cents is 0).'

        Claim: after REJECT, dispute.status=RESOLVED_REJECTED and
        outcome_amount_cents=0.
        """
        machine, _, courier, parcel = setup_deposited_parcel()
        opened = validate_success(api.open_dispute(
            parcel["id"], open_dispute_payload(claim_type="DAMAGED"),
            make_courier_headers(courier["id"]),
        ), expected_status=201)
        resp = api.resolve_dispute(
            opened["id"],
            resolve_dispute_payload(resolution="REJECT"),
            operations_admin_headers,
        )
        data = validate_success(resp)
        assert data["status"] == DisputeStatus.RESOLVED_REJECTED.value
        assert data["outcome_amount_cents"] == 0


class TestManualWaiveFee:
    """PRD §3.8: 'Operations may manually waive a fee in a few business
    situations. The waiver is permitted from UNPAID to WAIVED and
    requires a reason drawn from SYSTEM_FAULT, COURIER_WRONG_DEPOSIT, or
    MANUAL_DISPUTE.'"""

    def test_manual_waive_sets_parcel_fee_waived(
        self, api, operations_admin_headers,
    ):
        """PRD §3.8: 'The waiver sets Parcel.fee_waived to true and
        records the chosen reason in Parcel.fee_waiver_reason.'

        Claim: POST /parcels/{id}/waive-fee with reason=MANUAL_DISPUTE
        sets fee_waived=true and fee_waiver_reason=MANUAL_DISPUTE on the
        parcel.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        api.waive_fee(
            parcel["id"], waive_fee_payload(reason="MANUAL_DISPUTE"),
            operations_admin_headers,
        )
        again = get_parcel(parcel["id"])
        assert again["fee_waived"] is True
        assert again["fee_waiver_reason"] == (
            FeeWaiverReason.MANUAL_DISPUTE.value
        )
