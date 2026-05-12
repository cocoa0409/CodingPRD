"""Overtime fee tiered pricing — PRD §3.5, §2.8."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FEE_CAP_CENTS,
    FREE_HOURS,
    OvertimeFeePaymentStatus,
    OvertimeFeeVariant,
    TIER1_END_HOURS,
    TIER1_RATE_CENTS,
    TIER2_END_HOURS,
    TIER2_RATE_CENTS,
    TIER3_RATE_CENTS,
    advance_clock,
    advance_hours,
    assert_amount_cents,
    assert_overtime_fee_record,
    deposit_parcel,
    emit_event_payload,
    get_fee_records,
    get_parcel,
    initiate_pickup,
    initiate_pickup_payload,
    latest_final_fee,
    latest_provisional_fee,
    make_recipient_headers,
    pay_fee_record,
    payment_succeeded_payload,
    pickup_confirm,
    setup_basic_scenario,
    setup_deposited_parcel,
    setup_picked_up_parcel,
    setup_pickup_pending_parcel,
    validate_error,
    validate_success,
)


class TestFreeStorageBoundary:
    """PRD §3.5: 'The first 24 elapsed hours are free; that is the
    FREE_HOURS constant.'"""

    def test_zero_fee_at_24_hours_inclusive(self, api):
        """PRD §3.5: 'The first 24 elapsed hours are free; that is the
        FREE_HOURS constant.'

        Claim: at elapsed_hours == 24 (the inclusive end of the free
        period), the provisional fee is exactly 0.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(FREE_HOURS)  # 24h exact
        result = initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == 0, (
            f"PRD §3.5 free period: at 24h, fee must be 0; got "
            f"{prov['amount_cents']}"
        )

    def test_one_cent_per_hour_at_25_hours(self, api):
        """PRD §3.5: 'Hours from the 25th up to the 72nd accrue at the
        tier-one rate of 100 cents per hour.'

        Claim: at elapsed_hours == 25 the provisional fee is exactly
        1 * 100 = 100 cents.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(FREE_HOURS + 1)  # 25h
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == TIER1_RATE_CENTS, (
            f"expected {TIER1_RATE_CENTS}; got {prov['amount_cents']}"
        )


class TestTierBoundaries:
    """PRD §3.5: 'Hours from the 25th up to the 72nd accrue at the
    tier-one rate of 100 cents per hour … Hours from the 73rd up to the
    168th accrue at the tier-two rate of 200 cents per hour … Hours
    beyond the 168th accrue at the tier-three rate of 400 cents per
    hour.'"""

    def test_tier1_full_at_72_hours(self, api):
        """PRD §3.5: 'Hours from the 25th up to the 72nd accrue at the
        tier-one rate of 100 cents per hour.'

        Claim: at elapsed_hours == 72, fee = (72-24) * 100 = 4800 cents.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(TIER1_END_HOURS)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        expected = (TIER1_END_HOURS - FREE_HOURS) * TIER1_RATE_CENTS
        assert prov["amount_cents"] == expected, (
            f"PRD §3.5: at 72h, expected {expected}; got {prov['amount_cents']}"
        )

    def test_tier2_at_73_hours(self, api):
        """PRD §3.5: 'Hours from the 25th up to the 72nd accrue at the
        tier-one rate of 100 cents per hour … Hours from the 73rd up to
        the 168th accrue at the tier-two rate of 200 cents per hour.'

        Claim: at elapsed_hours == 73, fee =
        48 * 100 (full tier1) + 1 * 200 (one tier2 hour) = 5000 cents.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(TIER1_END_HOURS + 1)  # 73h
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        expected = (
            (TIER1_END_HOURS - FREE_HOURS) * TIER1_RATE_CENTS
            + 1 * TIER2_RATE_CENTS
        )
        assert prov["amount_cents"] == expected, (
            f"PRD §3.5: at 73h, expected {expected}; got {prov['amount_cents']}"
        )


class TestFeeCap:
    """PRD §3.5: 'The final amount_cents is the smaller of this raw sum
    and the hard cap FEE_CAP_CENTS of 10000 cents (one hundred dollars).'"""

    def test_fee_capped_at_10000_cents_after_100h(self, api):
        """PRD §3.5: 'The final amount_cents is the smaller of this raw
        sum and the hard cap FEE_CAP_CENTS of 10000 cents (one hundred
        dollars).'

        Claim: at elapsed_hours == 100,
        raw = 48*100 (tier1) + 28*200 (tier2) = 4800 + 5600 = 10400,
        capped to FEE_CAP_CENTS = 10000.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(100)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        assert prov["amount_cents"] == FEE_CAP_CENTS, (
            f"PRD §3.5 cap: expected {FEE_CAP_CENTS}; got "
            f"{prov['amount_cents']}"
        )


class TestProvisionalVsFinal:
    """PRD §3.5: 'Provisional and final amounts may differ when a tier
    boundary is crossed in the interval between PICKUP_PENDING entry and
    actual pickup.'"""

    def test_final_strictly_greater_when_tier_crossed(self, api):
        """PRD §3.5: 'Provisional and final amounts may differ when a
        tier boundary is crossed in the interval between PICKUP_PENDING
        entry and actual pickup; in that case the final amount is
        strictly larger.'

        Claim: deposit, initiate-pickup at 71h (PROVISIONAL=4700),
        pay, advance another 2h (now 73h elapsed), pickup-confirm →
        FINAL=5000. FINAL > PROVISIONAL.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        advance_hours(71)
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None
        prov_amount = prov["amount_cents"]
        # Pay the provisional fee
        pay_fee_record(prov["id"])
        advance_hours(2)  # cross into tier2
        headers = make_recipient_headers(parcel["recipient_phone"])
        api.pickup_confirm(parcel["id"], headers)
        final = latest_final_fee(parcel["id"])
        assert final is not None
        final_amount = final["amount_cents"]
        # PROVISIONAL@71h: (71-24)*100 = 4700
        # FINAL@73h: 48*100 + 1*200 = 5000
        assert prov_amount == 4700, (
            f"expected PROVISIONAL=4700@71h; got {prov_amount}"
        )
        assert final_amount == 5000, (
            f"expected FINAL=5000@73h; got {final_amount}"
        )
        assert final_amount > prov_amount, (
            "PRD §3.5: 'the final amount is strictly larger'"
        )


class TestZeroFeeNotPayable:
    """PRD §3.8: 'a zero-amount fee record cannot be marked paid; the
    attempt is rejected with ERR_FEE_ZERO_NOT_PAYABLE.'"""

    def test_zero_fee_payment_succeeded_rejected(self, api):
        """PRD §3.8: 'a zero-amount fee record cannot be marked paid; the
        attempt is rejected with ERR_FEE_ZERO_NOT_PAYABLE.'

        Claim: emitting payment_succeeded against a 0-cent
        OvertimeFeeRecord (within free 24h) returns
        ERR_FEE_ZERO_NOT_PAYABLE.
        """
        machine, _, _, parcel = setup_deposited_parcel()
        # Within free hours — provisional fee is 0
        initiate_pickup(parcel, method="CODE")
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None and prov["amount_cents"] == 0
        # Now attempt to pay — should fail.
        from test_helpers import payment_succeeded_payload, TEST_USERS
        resp = api.emit_event(
            payment_succeeded_payload(fee_record_id=prov["id"]),
            TEST_USERS["operations_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FEE_ZERO_NOT_PAYABLE.value)


class TestPaymentIdempotency:
    """PRD §3.8: 'a replay of the same event (same external id) returns
    200 with no double credit; a different external id targeting the
    same record is rejected with ERR_DUPLICATE_PAYMENT_EVENT.'"""

    def test_different_external_id_same_record_returns_duplicate(self, api):
        """PRD §3.8: 'a different external id targeting the same record
        is rejected with ERR_DUPLICATE_PAYMENT_EVENT.'

        Claim: paying a fee record with one external id, then re-emitting
        with a different external id, returns ERR_DUPLICATE_PAYMENT_EVENT.
        """
        from test_helpers import unique_external_id, TEST_USERS

        machine, courier, parcel = setup_pickup_pending_parcel(
            elapsed_hours=25,
        )
        prov = latest_provisional_fee(parcel["id"])
        assert prov is not None and prov["amount_cents"] > 0
        ext_a = unique_external_id("ext-a")
        api.emit_event(
            payment_succeeded_payload(
                fee_record_id=prov["id"], payment_external_id=ext_a,
            ),
            TEST_USERS["operations_admin_headers"],
        )
        ext_b = unique_external_id("ext-b")
        resp = api.emit_event(
            payment_succeeded_payload(
                fee_record_id=prov["id"], payment_external_id=ext_b,
            ),
            TEST_USERS["operations_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PAYMENT_EVENT.value)
