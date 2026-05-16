"""Cancellation and tiered refund tests.

Covers PRD §3.8 — tier table boundary precision, per-line rounded
refund, channel variant (SELF vs OFFICIAL), money conservation
invariant, and per-tier refund_channel labelling.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    admin_cancel,
    advance_clock_to,
    api_client,
    assert_money_invariant,
    assert_refund_transaction,
    create_candidate,
    create_event_with_capacity,
    create_test_event,
    create_test_center,
    create_capacity,
    force_confirmed_registration,
    make_candidate_headers,
    per_line_refund_cents,
    refund_tier_for_days,
    reset_clock_to,
    round_half_up_to_int,
    self_cancel,
    setup_registration_at_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Tier boundary table (days_before_test thresholds)
# ===========================================================================
class TestTierBoundary:
    def test_thirty_days_exact_hits_full_tier(self, api):
        """PRD §3.8: "when `days_before_test` is at least 30 the tier
        is `FULL` with a rate of 1.00".

        Claim: cancellation at days_before_test == 30 yields
        tier_label=FULL, amount_cents == base_fee_cents (rate 1.00).
        """
        event, center, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-05-08T09:00:00.000Z",  # exactly 30 days
        )
        cancelled = self_cancel(event["id"], reg, cand)
        assert cancelled["status"] == "CANCELLED"
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        assert len(rows) == 1
        refund = rows[0]
        assert_refund_transaction(refund)
        assert refund["tier_label"] == "FULL", (
            "PRD §3.8: days_before_test == 30 hits the >= 30 boundary -> FULL"
        )
        assert refund["amount_cents"] == 6000

    def test_twenty_nine_days_hits_partial_75(self, api):
        """PRD §3.8: "when `days_before_test` is at least 15 and less
        than 30 the tier is `PARTIAL_75` with a rate of 0.75".

        Claim: cancellation at days_before_test == 29 yields
        tier_label=PARTIAL_75, amount_cents == 4500 for base_fee=6000.
        """
        event, center, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-05-10T09:00:00.000Z",  # 29 days before
        )
        cancelled = self_cancel(event["id"], reg, cand)
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        refund = rows[0]
        assert refund["tier_label"] == "PARTIAL_75"
        assert refund["amount_cents"] == 4500, (
            "PRD §3.8: 6000 * 0.75 = 4500 (round half-up on integer product)"
        )

    def test_less_than_seven_days_yields_none_tier_zero_refund(self, api):
        """PRD §3.8: "when `days_before_test` is less than 7 the tier
        is `NONE` with a rate of 0.00."

        Claim: cancellation at days_before_test == 6 yields tier=NONE
        and amount_cents == 0.
        """
        event, center, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",  # 6 days before
        )
        self_cancel(event["id"], reg, cand)
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        refund = rows[0]
        assert refund["tier_label"] == "NONE"
        assert refund["amount_cents"] == 0


# ===========================================================================
# Per-line rounding pinned (PRD §2.6 / §3.8)
# ===========================================================================
class TestPerLineRoundingOrder:
    def test_per_line_rounding_observable_in_amount(self, api):
        """PRD §2.6: "Where the refund computation produces multiple
        per-line products, each line is rounded half-up to whole cents
        individually and only then summed — the order is fixed as
        round-then-sum rather than sum-then-round, and this ordering
        is observable in the recorded `RefundTransaction.amount_cents`."

        Claim: base=5999, late=3001, rate=0.50 yields per-line
        5999*0.5=2999.5 -> 3000 plus 3001*0.5=1500.5 -> 1501 = 4501.
        Sum-then-round would give 9000*0.5=4500.
        """
        # days_before_test = 8 -> PARTIAL_50 rate=0.50
        # Set test_date so the cancellation lands at 8 days before.
        event, center, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-23T09:00:00.000Z",
            base_fee_cents=5999, late_fee_cents=3001,
            clock_at_creation_iso="2026-06-15T09:00:00.000Z",  # 8 days before
            # Force the registration to be in the late window so late_fee is captured.
            registration_deadline_iso="2026-05-25T00:00:00.000Z",
            late_registration_deadline_iso="2026-06-20T00:00:00.000Z",
        )
        # Sanity: registration should have base+late captured.
        assert reg["base_fee_cents_charged"] == 5999
        assert reg["late_fee_cents_charged"] == 3001
        self_cancel(event["id"], reg, cand)
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        refund = rows[0]
        assert refund["tier_label"] == "PARTIAL_50"
        assert refund["amount_cents"] == 4501, (
            "PRD §2.6/§3.8: per-line round-then-sum yields 3000+1501=4501; "
            "sum-then-round would yield 4500"
        )


# ===========================================================================
# Channel variant: official cancellation forces rate 1.00 but keeps actual tier label
# ===========================================================================
class TestChannelVariant:
    def test_official_cancellation_forces_full_refund(self, api):
        """PRD §3.8: "For official cancellations — a `Registrar`
        cancelling for reasons such as event mis-scheduling, force
        majeure, or a downstream ID rejection cascade — the rate is
        forced to 1.00 on both the base fee and the late fee regardless
        of `days_before_test`".

        Claim: admin-cancel at days_before_test=6 (would be tier NONE)
        still produces amount_cents == base+late (no refund-tier rate).
        """
        event, center, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",  # 6 days before
        )
        admin_cancel(event["id"], reg["id"])
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        refund = rows[0]
        assert refund["refund_channel"] == "OFFICIAL_CANCELLATION"
        assert refund["amount_cents"] == 6000, (
            "PRD §3.8: official cancellation forces rate 1.00 on base + late"
        )

    def test_official_tier_label_records_actual_time_tier(self, api):
        """PRD §3.8: "The tier label that gets written into the
        resulting `RefundTransaction.tier_label` is, in both variants,
        the actual time-tier (`FULL`, `PARTIAL_75`, `PARTIAL_50`, or
        `NONE`) that would have applied at the cancellation instant —
        not a synthetic value reflecting the forced rate".

        Claim: admin-cancel at days_before_test=6 records
        tier_label=NONE even though the rate was forced to 1.00.
        """
        event, center, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-08T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=0,
            clock_at_creation_iso="2026-06-02T09:00:00.000Z",
        )
        admin_cancel(event["id"], reg["id"])
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        refund = rows[0]
        assert refund["tier_label"] == "NONE", (
            "PRD §3.8: tier_label records the actual time-tier even when "
            "the official-cancellation rate override applies"
        )


# ===========================================================================
# Accommodation fee never refunded
# ===========================================================================
class TestAccommodationFeeNonRefundable:
    def test_accommodation_fee_retained_on_full_tier(self, api):
        """PRD §3.8: "the refund on the accommodation fee is always
        zero, because the accommodation processing fee is non-refundable
        regardless of tier or channel."

        Claim: a candidate with accommodation_fee_cents_charged=2500
        cancelled in the FULL tier window has amount_refunded_cents
        equal to base+late (2500 retained as accommodation fee).
        """
        from test_helpers import submit_and_approve_accommodation
        event, center, _ = create_event_with_capacity(
            test_date="2026-06-08T09:00:00.000Z",
            registration_deadline="2026-05-25T00:00:00.000Z",
            late_registration_deadline="2026-06-04T00:00:00.000Z",
            score_release_date="2026-06-15T00:00:00.000Z",
            total_capacity=5, accommodation_capacity=2,
        )
        reset_clock_to("2026-05-01T00:00:00.000Z")
        cand = create_candidate(has_iep_or_504=True, home_state_code="CA")
        reg = force_confirmed_registration(event["id"], cand, center["id"])
        # Approve accommodation so accommodation fee is added.
        submit_and_approve_accommodation(cand, event["id"])
        refreshed = validate_success(
            api.get_registration(event["id"], reg["id"],
                                 TEST_USERS["registrar_headers"]),
            200,
        )
        assert refreshed["accommodation_fee_cents_charged"] == 2500
        amount_charged = refreshed["amount_charged_cents"]
        # Cancel at FULL tier (still in May, days_before_test >= 30 not satisfied
        # since clock at 2026-05-01 vs test_date 2026-06-08 is 38 days).
        cancelled = self_cancel(event["id"], refreshed, cand)
        rows, _ = validate_paginated(
            api.list_refunds(event["id"], reg["id"],
                             TEST_USERS["registrar_headers"]),
        )
        refund = rows[0]
        # Refund = base*1.0 + late*1.0 + 0 (accommodation never refunded).
        expected = (refreshed["base_fee_cents_charged"]
                    + refreshed["late_fee_cents_charged"])
        assert refund["amount_cents"] == expected, (
            "PRD §3.8: accommodation fee is non-refundable; refund equals base + late only"
        )
        assert cancelled["amount_refunded_cents"] == expected
        # Money conservation: charged == refunded + retained, retained includes accommodation fee.
        assert cancelled["amount_retained_cents"] == amount_charged - expected
        assert_money_invariant(cancelled)


# ===========================================================================
# Money conservation after the cascade
# ===========================================================================
class TestMoneyConservation:
    def test_money_invariant_after_partial_refund(self, api):
        """PRD §3.4 / §3.8: "`amount_retained_cents` is recomputed as
        `amount_charged_cents` minus `amount_refunded_cents`."

        Claim: amount_charged == amount_refunded + amount_retained both
        before and after a partial-tier cancellation.
        """
        # base=6000, late=2000 in a PARTIAL_50 window -> refund = 3000 + 1000 = 4000.
        event, center, cand, reg = setup_registration_at_clock(
            test_date_iso="2026-06-23T09:00:00.000Z",
            base_fee_cents=6000, late_fee_cents=2000,
            clock_at_creation_iso="2026-06-15T09:00:00.000Z",  # 8 days
            registration_deadline_iso="2026-05-25T00:00:00.000Z",
            late_registration_deadline_iso="2026-06-20T00:00:00.000Z",
        )
        # Pre-cancel invariant.
        assert reg["amount_charged_cents"] == 8000
        assert_money_invariant(reg)
        cancelled = self_cancel(event["id"], reg, cand)
        assert cancelled["amount_refunded_cents"] == 4000
        assert cancelled["amount_retained_cents"] == 4000
        assert_money_invariant(cancelled)


# ===========================================================================
# Cancellation after event COMPLETED forbidden
# ===========================================================================
class TestCancelAfterCompletedForbidden:
    def test_cancel_after_event_completed_rejected(self, api):
        """PRD §3.8: "Cancellation is forbidden once the parent
        `TestEvent` has reached `COMPLETED`; an attempt is rejected
        with `ERR_INVALID_REGISTRATION_STATE`."

        Claim: a self-cancel call against a registration whose event
        has reached COMPLETED returns ERR_INVALID_REGISTRATION_STATE.
        """
        from test_helpers import complete_registration_lifecycle
        cand = create_candidate()
        event, reg = complete_registration_lifecycle(cand)
        assert event["status"] == "COMPLETED"
        # Registration is now COMPLETED, not CONFIRMED/STANDBY — attempt cancel.
        res = api.self_cancel_registration(
            event["id"], reg["id"],
            make_candidate_headers(cand["id"]),
            {},
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value)
