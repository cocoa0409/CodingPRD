"""Wrong-deposit correction — PRD §3.6 + cascade hops 1–3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    CompartmentStatus,
    CorrectionOrigin,
    CourierBlacklistStatus,
    FeeWaiverReason,
    OvertimeFeePaymentStatus,
    OvertimeFeeVariant,
    ParcelStatus,
    WRONG_DEPOSIT_GRACE_SECONDS,
    advance_clock,
    advance_hours,
    correct_wrong_deposit_payload,
    create_courier,
    deposit_parcel,
    get_compartment,
    get_courier,
    get_parcel,
    initiate_pickup,
    latest_provisional_fee,
    make_courier_headers,
    setup_basic_scenario,
    setup_courier_with_window_wrong_rate,
    setup_deposited_parcel,
    setup_picked_up_parcel,
    setup_pickup_pending_parcel,
    validate_error,
    validate_success,
)


class TestWrongDepositGraceWindow:
    """PRD §3.6: 'within a short grace window of 900 seconds
    (WRONG_DEPOSIT_GRACE_SECONDS) measured from deposited_at.'"""

    def test_correction_after_grace_expired_rejected(self, api):
        """PRD §3.6: 'the elapsed time since deposit must be strictly less
        than the grace window, otherwise the request is rejected with
        ERR_WRONG_DEPOSIT_GRACE_EXPIRED.'

        Claim: 901 seconds after deposit, /correct-wrong-deposit returns
        ERR_WRONG_DEPOSIT_GRACE_EXPIRED.
        """
        machine, _, courier, parcel = setup_deposited_parcel()
        advance_clock(WRONG_DEPOSIT_GRACE_SECONDS + 1)
        resp = api.correct_wrong_deposit(
            parcel["id"],
            correct_wrong_deposit_payload(),
            make_courier_headers(courier["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_WRONG_DEPOSIT_GRACE_EXPIRED.value,
        )


class TestWrongDepositOwnership:
    """PRD §3.6: 'the acting X-User-ID must equal the Parcel.courier_id
    of the original parcel, otherwise the request is rejected with
    ERR_NOT_COURIER_OWNER.'"""

    def test_correction_by_non_owner_rejected(self, api):
        """PRD §3.6: 'the acting X-User-ID must equal the Parcel.courier_id
        of the original parcel, otherwise the request is rejected with
        ERR_NOT_COURIER_OWNER.'

        Claim: another courier's headers calling /correct-wrong-deposit
        on a parcel they did not own returns ERR_NOT_COURIER_OWNER.
        """
        machine, _, owner, parcel = setup_deposited_parcel()
        intruder = create_courier()
        resp = api.correct_wrong_deposit(
            parcel["id"],
            correct_wrong_deposit_payload(),
            make_courier_headers(intruder["id"]),  # wrong courier
        )
        validate_error(resp, ApiErrorId.ERR_NOT_COURIER_OWNER.value)


class TestWrongDepositSuccessfulCorrection:
    """PRD §3.6: 'A successful correction sets the original parcel's
    status to WRONG_DEPOSIT_VOID, sets its fee_waived to true with
    fee_waiver_reason = COURIER_WRONG_DEPOSIT, and marks any provisional
    fee record on it as WAIVED.'"""

    def test_original_parcel_void_with_waived_fee(self, api):
        """PRD §3.6: 'A successful correction sets the original parcel's
        status to WRONG_DEPOSIT_VOID, sets its fee_waived to true with
        fee_waiver_reason = COURIER_WRONG_DEPOSIT.'

        Claim: after correction, the original parcel's status is
        WRONG_DEPOSIT_VOID, fee_waived is true, and fee_waiver_reason is
        COURIER_WRONG_DEPOSIT.
        """
        machine, _, courier, parcel = setup_deposited_parcel()
        api.correct_wrong_deposit(
            parcel["id"],
            correct_wrong_deposit_payload(),
            make_courier_headers(courier["id"]),
        )
        again = get_parcel(parcel["id"])
        assert again["status"] == ParcelStatus.WRONG_DEPOSIT_VOID.value
        assert again["fee_waived"] is True
        assert again["fee_waiver_reason"] == (
            FeeWaiverReason.COURIER_WRONG_DEPOSIT.value
        )

    def test_successor_parcel_created_with_correction_origin(self, api):
        """PRD §3.6: 'A successor Parcel is created on the same
        compartment with correction_origin = WRONG_DEPOSIT and
        replaces_parcel_id pointing back at the old parcel; the
        compartment stays OCCUPIED but its current_parcel_id is rebound
        to the successor.'

        Claim: the response carries the successor parcel; the successor's
        correction_origin is WRONG_DEPOSIT and replaces_parcel_id equals
        the original parcel's id; the compartment's current_parcel_id is
        rebound to the successor.
        """
        machine, _, courier, parcel = setup_deposited_parcel()
        resp = api.correct_wrong_deposit(
            parcel["id"],
            correct_wrong_deposit_payload(),
            make_courier_headers(courier["id"]),
        )
        successor = validate_success(resp)
        assert successor["correction_origin"] == (
            CorrectionOrigin.WRONG_DEPOSIT.value
        )
        assert successor["replaces_parcel_id"] == parcel["id"]
        comp = get_compartment(machine["id"], parcel["compartment_id"])
        assert comp["status"] == CompartmentStatus.OCCUPIED.value
        assert comp["current_parcel_id"] == successor["id"]


class TestWrongDepositWhenAdvancedRejected:
    """PRD §3.6: 'if the parcel has already advanced beyond DEPOSITED
    (for example, a recipient has begun pickup while the courier was
    preparing the correction), the request is rejected with
    ERR_PARCEL_STATE_CHANGED.'"""

    def test_correction_after_pickup_pending_rejected(self, api):
        """PRD §3.6: 'if the parcel has already advanced beyond DEPOSITED
        (for example, a recipient has begun pickup while the courier was
        preparing the correction), the request is rejected with
        ERR_PARCEL_STATE_CHANGED.'

        Claim: once the parcel is in PICKUP_PENDING (advanced past
        DEPOSITED), /correct-wrong-deposit returns ERR_PARCEL_STATE_CHANGED.
        """
        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=0,  # within grace window
        )
        resp = api.correct_wrong_deposit(
            parcel["id"],
            correct_wrong_deposit_payload(),
            make_courier_headers(courier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARCEL_STATE_CHANGED.value)


class TestWrongDepositReputationCascade:
    """PRD §3.6: 'If, after the recompute, the rolling rate is at least
    the blacklist threshold (BLACKLIST_THRESHOLD_RATE = 0.10, i.e. ten
    percent), the courier's blacklist_status auto-flips from ACTIVE to
    RESTRICTED.'"""

    def test_window_rate_at_threshold_flips_to_restricted(self, api):
        """PRD §3.6: 'If, after the recompute, the rolling rate is at
        least the blacklist threshold (BLACKLIST_THRESHOLD_RATE = 0.10,
        i.e. ten percent), the courier's blacklist_status auto-flips
        from ACTIVE to RESTRICTED.'

        Claim: after 9 successful deposits + 1 wrong-deposit correction
        in the current window (rate = 1/10 = 0.10), the courier's
        blacklist_status is RESTRICTED.
        """
        # Set up: 9 successful + 1 corrected → rate 1/10 = 0.10
        courier, _ = setup_courier_with_window_wrong_rate(
            deposits=10, wrong_deposits=1,
        )
        # Re-read so derived fields refresh
        again = get_courier(courier["id"])
        assert again["blacklist_status"] == (
            CourierBlacklistStatus.RESTRICTED.value
        ), (
            f"PRD §3.6 BLACKLIST_THRESHOLD_RATE=0.10: window rate=0.10 should "
            f"have flipped to RESTRICTED; got {again['blacklist_status']}"
        )
