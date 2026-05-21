"""Segment booking, marking flown, accrual formula, reversal invariant."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    SEGMENT_MAX_PER_SEGMENT,
    SEGMENT_MIN_PER_SEGMENT,
    booking_agent_headers,
    create_flight,
    create_member,
    create_member_with_balance,
    create_segment_for_member,
    depart_flight,
    expected_segment_accrual,
    filter_transactions_by_kind,
    fly_one_segment,
    get_member,
    get_segment,
    list_points_transactions,
    make_member_headers,
    mark_segment_flown,
    promote_member_to_tier_via_status_match,
    refund_segment,
    validate_error,
    validate_success,
)


class TestSegmentBooking:

    def test_create_segment_starts_in_booked(self, api):
        """PRD §3.3: "A cash booking creates a segment in BOOKED,
        recording the payload's flight_id and booked_cabin (one of
        ECONOMY, BUSINESS, or FIRST) and assigning the new row's
        member_id to the path member."
        """
        flight = create_flight()
        member = create_member()
        seg = create_segment_for_member(
            member["id"], flight["id"], booked_cabin="BUSINESS",
        )
        assert seg["status"] == "BOOKED"
        assert seg["booked_cabin"] == "BUSINESS"
        assert seg["member_id"] == member["id"]
        assert seg["flight_id"] == flight["id"]


class TestMarkFlown:

    def test_mark_flown_requires_flight_departed(self, api):
        """PRD §3.3: "A segment is marked flown by a BookingAgent (or by
        a ProgramAdmin) only when the underlying flight is in DEPARTED
        and the owning member is ACTIVE; otherwise
        ERR_SEGMENT_NOT_FLYABLE is returned."
        """
        flight = create_flight()
        member = create_member()
        seg = create_segment_for_member(member["id"], flight["id"])
        # Flight still SCHEDULED — mark-flown should fail.
        resp = api.mark_segment_flown(
            member["id"], seg["id"], booking_agent_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_FLYABLE.value)

    def test_mark_flown_appends_accrual_and_updates_counters(self, api):
        """PRD §3.3: "The transition to FLOWN records flown_cabin ...,
        records flown_year as the calendar year of Flight.departure_at,
        and appends one ACCRUAL row to the points ledger. ... The
        member's points_balance is incremented by the same amount via
        the ledger sum; current_year_qualifying_segments is incremented
        by one and current_year_qualifying_points is incremented by
        qualifying_points_earned."
        """
        member = create_member()
        flight, flown = fly_one_segment(
            member["id"],
            flight_overrides={"base_fare_cents": 50_000},  # $500
        )
        # Expected accrual at BASIC, ECONOMY: 500 * 5 * 1.0 = 2500.
        expected = expected_segment_accrual(50_000, "ECONOMY", "BASIC")
        assert expected == 2_500
        assert flown["qualifying_points_earned"] == expected
        member_after = get_member(member["id"])
        assert member_after["points_balance"] == expected
        assert member_after["current_year_qualifying_segments"] == 1
        assert member_after["current_year_qualifying_points"] == expected


class TestAccrualFormulaBoundaries:

    def test_min_per_segment_floor_lifts_to_100(self, api):
        """PRD §3.3: "if it is below the per-segment floor of 100
        points, raise it to 100."

        At BASIC tier, ECONOMY cabin, base_fare_cents=1000 ($10) → raw
        = 10 * 5 * 1.0 = 50; clamped up to 100.
        """
        member = create_member()
        _, flown = fly_one_segment(
            member["id"],
            flight_overrides={"base_fare_cents": 1_000},
            booked_cabin="ECONOMY",
        )
        assert flown["qualifying_points_earned"] == SEGMENT_MIN_PER_SEGMENT, (
            "PRD §3.3: raw 50 below MIN_PER_SEGMENT 100 → clamp up to 100"
        )

    def test_max_per_segment_ceiling_caps_at_50000(self, api):
        """PRD §3.3: "if it is above the per-segment ceiling of 50 000
        points, lower it to 50 000."

        # difficulty: combinatorial_formula/segment_accrual_four_input_nonlinear_mode_a
        Claim: at PLATINUM tier, FIRST cabin, base_fare_cents=400_000
        ($4000) the raw product is 4000*12*2.0 = 96_000, capped at
        50_000.
        """
        # Promote to PLATINUM via status match.
        member = create_member()
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="PLATINUM",
        )
        _, flown = fly_one_segment(
            member["id"],
            flight_overrides={"base_fare_cents": 400_000},
            booked_cabin="FIRST",
        )
        assert flown["qualifying_points_earned"] == SEGMENT_MAX_PER_SEGMENT, (
            "PRD §3.3: raw 96_000 above MAX_PER_SEGMENT 50_000 → clamp "
            "down to 50_000"
        )

    @pytest.mark.parametrize(
        "tier,cabin,base_fare_cents,expected",
        [
            # Each row computed from the formula:
            # base_dollars * fare_class_mult * tier_bonus_mult, floor, clamp.
            ("BASIC",    "ECONOMY",  200_000,  10_000),  # 2000*5*1.0
            ("SILVER",   "ECONOMY",   20_000,   1_250),  # 200*5*1.25
            ("GOLD",     "BUSINESS", 100_000,  15_000),  # 1000*10*1.5
            ("PLATINUM", "BUSINESS", 100_000,  20_000),  # 1000*10*2.0
        ],
    )
    def test_accrual_formula_matches_pinned_table(self, api, tier,
                                                   cabin, base_fare_cents,
                                                   expected):
        """PRD §3.3 segment accrual formula — multiplicative product
        floored and clamped. Tier-bonus and fare-class lookup tables
        are pinned in PRD prose.
        """
        member = create_member()
        if tier != "BASIC":
            member = promote_member_to_tier_via_status_match(
                member["id"], target_tier=tier,
            )
        _, flown = fly_one_segment(
            member["id"],
            flight_overrides={"base_fare_cents": base_fare_cents},
            booked_cabin=cabin,
        )
        assert flown["qualifying_points_earned"] == expected


class TestQualifyingSegmentReversal:

    def test_refund_reverses_counters_and_balance(self, api):
        """PRD §3.3 conservation contract:
        "let q0 be the year's qualifying-segment count before the
        original FLOWN, let q1 be the count immediately after FLOWN, and
        let q2 be the count immediately after REFUNDED; then q2 must
        equal q0, and the member's points_balance after the refund must
        equal its value immediately before FLOWN."

        # difficulty: compensating_invariant/qualifying_segments_conserved_under_fly_then_refund
        """
        member = create_member_with_balance(0)
        q0_segments = 0
        q0_points = 0
        balance_before_flown = 0
        flight, flown = fly_one_segment(
            member["id"],
            flight_overrides={"base_fare_cents": 20_000},
            booked_cabin="ECONOMY",
        )
        accrued = flown["qualifying_points_earned"]
        member_after_flown = get_member(member["id"])
        assert member_after_flown["current_year_qualifying_segments"] == 1
        assert member_after_flown["current_year_qualifying_points"] == accrued
        assert member_after_flown["points_balance"] == balance_before_flown + accrued
        # Refund.
        refunded = refund_segment(member["id"], flown["id"])
        assert refunded["status"] == "REFUNDED"
        member_after_refund = get_member(member["id"])
        assert member_after_refund["current_year_qualifying_segments"] == q0_segments, (
            "PRD §3.3: q2 must equal q0 (qualifying segments restored)"
        )
        assert member_after_refund["current_year_qualifying_points"] == q0_points
        assert member_after_refund["points_balance"] == balance_before_flown, (
            "PRD §3.3: the member's points_balance after the refund "
            "must equal its value immediately before FLOWN."
        )

    def test_refund_writes_negative_accrual_row(self, api):
        """PRD §3.3: "The refund transition produces the single
        negative ACCRUAL the ledger ever allows: a row of kind ACCRUAL
        with points_delta equal to -qualifying_points_earned and
        qualifying_points likewise negated, posted at the refund
        instant."
        """
        member = create_member()
        _, flown = fly_one_segment(
            member["id"], flight_overrides={"base_fare_cents": 20_000},
        )
        refund_segment(member["id"], flown["id"])
        ledger = list_points_transactions(member["id"])
        accruals = filter_transactions_by_kind(ledger, "ACCRUAL")
        # Should have exactly two ACCRUAL rows: +accrued and -accrued.
        assert len(accruals) == 2
        deltas = sorted(int(a["points_delta"]) for a in accruals)
        assert deltas[0] == -flown["qualifying_points_earned"]
        assert deltas[1] == flown["qualifying_points_earned"]


class TestSegmentCancel:

    def test_cancel_booked_segment_before_departure_allowed(self, api):
        """PRD §3.3: "A BOOKED segment can be cancelled before the
        flight departs. Cancellation is allowed only while Flight.status
        is SCHEDULED."
        """
        flight = create_flight()
        member = create_member()
        seg = create_segment_for_member(member["id"], flight["id"])
        data = validate_success(
            api.cancel_segment(member["id"], seg["id"],
                                make_member_headers(member["id"]))
        )
        assert data["status"] == "CANCELLED"
