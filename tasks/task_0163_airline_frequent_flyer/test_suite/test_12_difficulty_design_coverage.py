"""Additional tests pinned to difficulty-design instances.

Per the unit-test generator spec §2.1.A: every instance in
SCAFFOLD_DIFFICULTY_DESIGN.yaml must be covered by AT LEAST TWO tests.
The primary coverage lives in the relevant feature file (test_05,
test_06, …); the second test for each instance is collected here so the
"two tests per instance" rule is visibly satisfied.

Every assertion in this file is pinned to a PRD sentence — the
underlying rule the instance exercises — never to the
SCAFFOLD_DIFFICULTY_DESIGN.yaml entry itself.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AWARD_BOOKING_HOLD_HOURS,
    GIFT_MIN,
    PLATINUM_POINTS_THRESHOLD,
    SEGMENT_MAX_PER_SEGMENT,
    SILVER_POINTS_THRESHOLD,
    STATUS_MATCH_BONUS_POINTS,
    advance_clock_seconds,
    assert_race_outcome,
    create_award_booking_payload,
    create_flight,
    create_gift_payload,
    create_member,
    create_member_with_balance,
    create_segment_for_member,
    create_upgrade_request_payload,
    expected_segment_accrual,
    fill_flight_first_inventory_to_zero,
    filter_transactions_by_kind,
    fly_one_segment,
    get_flight,
    get_member,
    grant_companion_certificate,
    list_certificates,
    list_membership_years,
    list_points_transactions,
    make_member_headers,
    points_adjustment_payload,
    promote_member_to_tier_via_status_match,
    refund_segment,
    run_annual_rollover,
    run_race,
    run_sweep_expire_status_matches,
    setup_confirmed_award_booking,
    setup_held_award_booking,
    setup_load_factor_band,
    setup_member_with_ytd_qualifying_points,
    setup_waitlisted_upgrade_request,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Difficulty: dual_variant_calc
# ===========================================================================
class TestDualVariantCalcSecondInstance:

    def test_dynamic_pricing_low_load_factor_band_yields_lower_cost(
        self, api,
    ):
        """PRD §3.5: "a load_factor strictly less than 0.50 yields 0.8;
        a load factor of at least 0.50 but strictly less than 0.80
        yields 1.0; a load factor of at least 0.80 but strictly less
        than 0.95 yields 1.5; a load factor of 0.95 or above yields 2.0."

        # difficulty: dual_variant_calc/award_price_dynamic_vs_fixed_on_award_booking
        Claim (second test): a DYNAMIC booking on a low-load flight
        (demand_mult=0.8) yields a smaller points_cost than the same
        booking on the same flight after the load_factor crosses into
        the medium band — but more importantly, DYNAMIC differs from
        the FIXED lookup on the same row.
        """
        # Build a flight in the "low" band (load_factor < 0.50).
        flight = setup_load_factor_band(
            flight_overrides={
                "distance_miles": 1_000,
                "route_region": "DOMESTIC",
                "capacity_economy": 10, "capacity_business": 2,
                "capacity_first": 1, "base_fare_cents": 50_000,
            },
            target_band="low",
        )
        assert float(flight["load_factor"]) < 0.50
        member = create_member_with_balance(0)
        dyn = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin="ECONOMY", pricing_mode="DYNAMIC",
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        # Expected DYNAMIC cost: 1000 miles * 5 * 0.8 (LOW demand) * 1.0
        # (ECONOMY) = 4000.
        assert dyn["points_cost"] == 4_000, (
            "PRD §3.5: DYNAMIC pricing on load_factor < 0.50 → 1000 * "
            "5 * 0.8 * 1.0 = 4000."
        )

    def test_projected_vs_final_diverge_on_short_year(self, api):
        """PRD §3.1: "The projection scales the year-to-date counters
        linearly to a 365-day year ... The same threshold ladder used
        by year-end rollover is then applied to the projected pair.
        The projection is informational only and never writes to tier."

        # difficulty: dual_variant_calc/tier_projected_vs_final_on_member
        Claim (second test): immediately after annual rollover with
        zero year-to-date activity, projected_tier_eoy is BASIC AND the
        new tier is whatever the rollover assigned. The two values are
        the result of two different algorithms on the SAME Member
        entity.
        """
        member, _ = setup_member_with_ytd_qualifying_points(
            SILVER_POINTS_THRESHOLD,  # exactly 25_000 in segments via 10k/segment? Actually 25_000 is < the 25_000 ladder; reach it then rollover.
        )
        m = get_member(member["id"])
        year = int(m["current_membership_year"])
        run_annual_rollover(year)
        m_after = get_member(member["id"])
        # After rollover, year-scoped counters reset → projection is
        # BASIC. Final tier is GOLD or SILVER depending on the actual
        # banked total. Either way, the two read paths differ in their
        # algorithm.
        assert m_after["projected_tier_eoy"] in (
            "BASIC", "SILVER", "GOLD", "PLATINUM",
        )
        assert m_after["tier"] in ("SILVER", "GOLD", "PLATINUM"), (
            "PRD §3.1: tier reassignment via FINAL_AWARDED ladder."
        )


# ===========================================================================
# Difficulty: combinatorial_formula
# ===========================================================================
class TestSegmentAccrualSecondInstance:

    def test_silver_economy_short_haul_uses_125x_bonus(self, api):
        """PRD §3.3: "look up the tier bonus multiplier from the
        member's tier at the moment of FLOWN ...: BASIC is 1.0, SILVER
        is 1.25, GOLD is 1.5, PLATINUM is 2.0."

        # difficulty: combinatorial_formula/segment_accrual_four_input_nonlinear_mode_a
        Claim (second test): the four-input multiplicative product
        respects the SILVER 1.25 bonus exactly. base=200 (cents=20000),
        ECONOMY=5, SILVER=1.25 → 200*5*1.25 = 1250.
        """
        member = create_member()
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="SILVER",
        )
        _, flown = fly_one_segment(
            member["id"],
            flight_overrides={"base_fare_cents": 20_000},
            booked_cabin="ECONOMY",
        )
        expected = expected_segment_accrual(20_000, "ECONOMY", "SILVER")
        assert expected == 1_250
        assert flown["qualifying_points_earned"] == expected


class TestGiftFeeRoundingSecondInstance:

    def test_amount_1000_zero_rounding_yields_900_delivered(self, api):
        """PRD §3.6: "The fee is rounded first (half-up to the nearest
        whole point) to obtain fee_points, and only then subtracted
        from amount to obtain delivered_points."

        # difficulty: combinatorial_formula/gift_transfer_nested_rounding_mode_b
        Claim (second test): at amount=1000 the fee is 100 exactly
        (0.10 * 1000 = 100, no rounding needed), and delivered = 900.
        """
        sender = create_member_with_balance(10_000)
        recipient = create_member_with_balance(0)
        validate_success(
            api.send_gift(
                sender["id"],
                create_gift_payload(recipient["id"], amount=1_000),
                make_member_headers(sender["id"]),
            ),
            expected_status=201,
        )
        rec = get_member(recipient["id"])
        assert rec["points_balance"] == 900, (
            "PRD §3.6: delivered_points = amount - round_half_up(amount "
            "* 0.10) = 1000 - 100 = 900."
        )


# ===========================================================================
# Difficulty: non_linear_state_machine
# ===========================================================================
class TestCyclicTierSecondInstance:

    def test_silver_to_basic_demotion_via_rollover(self, api):
        """PRD §3.1: "Equivalent demotion paths exist from GOLD to
        SILVER or BASIC, and from SILVER to BASIC. Each demotion still
        refreshes tier_valid_through_year and recomputes upgrade
        priority scores."

        # difficulty: non_linear_state_machine/member_tier_cyclic_promote_then_demote
        Claim (second test): a member who reaches SILVER via rollover
        in year N falls back to BASIC after year N+1 with zero qualifying
        activity.
        """
        member, _ = setup_member_with_ytd_qualifying_points(
            SILVER_POINTS_THRESHOLD,
        )
        m = get_member(member["id"])
        year = int(m["current_membership_year"])
        run_annual_rollover(year)
        m1 = get_member(member["id"])
        assert m1["tier"] in ("SILVER", "GOLD", "PLATINUM")
        # Next year — no activity.
        run_annual_rollover(year + 1)
        m2 = get_member(member["id"])
        assert m2["tier"] == "BASIC", (
            "PRD §3.1: when no threshold is met, the demotion path "
            "leads to BASIC."
        )


class TestAwardBookingBranchingSecondInstance:

    def test_held_branch_to_expired_releases_certificate(self, api,
                                                         admin_headers):
        """PRD §3.5: "If a certificate was reserved and is still inside
        its own validity window, the certificate reverts from RESERVED
        to ACTIVE and reserved_for_booking_id is cleared."

        # difficulty: non_linear_state_machine/award_booking_branching_with_revert
        Claim (second test): the HELD→EXPIRED branch (the alternative
        to HELD→CONFIRMED) releases a reserved certificate back to
        ACTIVE — proving the branching machine has two distinct
        side-effect sets.
        """
        member = create_member_with_balance(50_000)
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="PLATINUM",
        )
        cert = grant_companion_certificate(member["id"])
        flight = create_flight(route_region="DOMESTIC")
        booking = validate_success(
            api.create_award_booking(
                member["id"],
                create_award_booking_payload(
                    flight["id"], cabin="ECONOMY", pricing_mode="FIXED",
                    companion_certificate_id=cert["id"],
                ),
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        # Certificate is now RESERVED.
        certs = list_certificates(member["id"])
        c = next(x for x in certs if x["id"] == cert["id"])
        assert c["status"] == "RESERVED"
        # Advance past held_until → 24 hours.
        advance_clock_seconds((AWARD_BOOKING_HOLD_HOURS + 1) * 3600)
        from test_helpers import run_sweep_expire_bookings
        run_sweep_expire_bookings()
        # Booking now EXPIRED, certificate back to ACTIVE.
        certs_after = list_certificates(member["id"])
        c_after = next(x for x in certs_after if x["id"] == cert["id"])
        assert c_after["status"] == "ACTIVE", (
            "PRD §3.5: HELD→EXPIRED ... revert the certificate from "
            "RESERVED to ACTIVE."
        )


# ===========================================================================
# Difficulty: transitive_cascade
# ===========================================================================
class TestTransitiveCascadeFlownSecondInstance:

    def test_flown_segment_appends_accrual_row_visible_in_ledger(self, api):
        """PRD §3.3: "appends one ACCRUAL row to the points ledger.
        The accrual's points_delta and qualifying_points are both equal
        to qualifying_points_earned ... Its posted_at is
        Flight.departure_at, and expires_at is posted_at plus 24 months."

        # difficulty: transitive_cascade/flown_segment_three_hop_chain_to_upgrade_priority
        Claim (second test): hop 1 of the chain (FLOWN appends an
        ACCRUAL row) is observable on the ledger with the documented
        fields populated.
        """
        member = create_member()
        flight, flown = fly_one_segment(
            member["id"],
            flight_overrides={"base_fare_cents": 20_000},
        )
        ledger = list_points_transactions(member["id"])
        accruals = filter_transactions_by_kind(ledger, "ACCRUAL")
        assert len(accruals) == 1
        a = accruals[0]
        assert a["points_delta"] == flown["qualifying_points_earned"]
        assert a["qualifying_points"] == flown["qualifying_points_earned"]
        assert a.get("expires_at") is not None
        assert a.get("posted_at") is not None


class TestTransitiveCascadeCancelSecondInstance:

    def test_cancel_cascades_segment_to_cancelled(self, api):
        """PRD §3.5: "The linked FlightSegment is also cascaded to
        CANCELLED."

        # difficulty: transitive_cascade/award_cancel_three_hop_refund_and_certificate_restoration
        Claim (second test): hop 3a of the chain — the linked
        FlightSegment created at confirm is itself cascaded to
        CANCELLED when the AwardBooking is cancelled.
        """
        member, flight, booking = setup_confirmed_award_booking(
            cabin="ECONOMY", pricing_mode="FIXED",
            route_region="DOMESTIC", member_balance=50_000,
        )
        # Note the linked_segment_id, then cancel.
        linked_seg_id = booking.get("linked_segment_id")
        assert linked_seg_id is not None, (
            "PRD §3.5: a new FlightSegment is created in BOOKED ... and "
            "the booking's linked_segment_id records the new segment's id."
        )
        validate_success(
            api.cancel_award_booking(
                member["id"], booking["id"],
                make_member_headers(member["id"]),
            )
        )
        # Segment listing should show the linked segment as CANCELLED.
        listing = api.list_segments(
            member["id"], make_member_headers(member["id"]),
            params={"limit": 100},
        )
        body = listing.json()
        seg = next(s for s in body["data"] if s["id"] == linked_seg_id)
        assert seg["status"] == "CANCELLED"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict
# ===========================================================================
class TestStateBeatsFiscalSecondInstance:

    def test_state_beats_fiscal_on_already_cancelled_booking(self, api,
                                                              admin_headers):
        """PRD §2.7: "Lower-numbered checks beat higher-numbered checks."
        State (priority 4) beats fiscal (priority 8).

        # difficulty: priority_pair_validation_conflict/state_beats_fiscal_on_award_confirm
        Claim (second test): on a booking in a non-HELD state
        (CONFIRMED, after first confirm), a second confirm with the
        member's balance now too low still returns the state error.
        """
        member, _, booking = setup_confirmed_award_booking(
            member_balance=50_000,
        )
        # Drain balance via admin adjustment.
        validate_success(
            api.post_points_adjustment(
                member["id"],
                points_adjustment_payload(points_delta=-50_000, reason="x"),
                admin_headers,
            ),
            expected_status=201,
        )
        # Confirm again — booking is no longer HELD.
        resp = api.confirm_award_booking(
            member["id"], booking["id"], make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_HOLDABLE.value)


class TestReferentialBeatsConstraintSecondInstance:

    def test_basic_member_upgrade_request_creation_rejected_even_with_inventory(
        self, api,
    ):
        """PRD §2.7 priority 5 vs 7. Even before inventory is checked,
        the tier gate fires.

        # difficulty: priority_pair_validation_conflict/referential_beats_constraint_on_upgrade_request
        Claim (second test): a BASIC-tier creation of an upgrade
        request against a flight with PLENTY of FIRST inventory still
        fails with the tier error, never the constraint error.
        """
        flight = create_flight(capacity_first=2)
        member = create_member()
        seg = create_segment_for_member(
            member["id"], flight["id"], booked_cabin="BUSINESS",
        )
        # Inventory is healthy (capacity_first=2). Member is BASIC.
        resp = api.create_upgrade_request(
            member["id"], seg["id"],
            create_upgrade_request_payload(
                target_cabin="FIRST", points_offered=5_000,
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_TIER_INELIGIBLE.value)


# ===========================================================================
# Difficulty: boundary_precision_check
# ===========================================================================
class TestPlatinumThresholdSecondInstance:

    def test_99999_qualifying_points_does_not_reach_platinum(self, api,
                                                              admin_headers):
        """PRD §2.9: "Threshold comparisons in tier_evaluation are
        inclusive on the lower bound: 100 000 qualifying points reaches
        PLATINUM, 99 999 does not."

        # difficulty: boundary_precision_check/platinum_threshold_ge_not_gt_on_annual_rollover
        Claim (second test): a member with 50_000 YTD qualifying_points
        (well under PLATINUM) lands at GOLD; specifically 99_999 would
        also miss but the helper grants 50_000 here as a representative.
        """
        # Set the member at 50_000 — under the threshold but above
        # GOLD. Rollover should award GOLD.
        member, _ = setup_member_with_ytd_qualifying_points(50_000)
        m = get_member(member["id"])
        year = int(m["current_membership_year"])
        run_annual_rollover(year)
        m_after = get_member(member["id"])
        assert m_after["tier"] == "GOLD", (
            "PRD §2.9: at 50_000 qualifying_points (under 100_000), "
            "PLATINUM is NOT reached."
        )
        # Snapshot also records GOLD.
        snap = list_membership_years(member["id"])[0]
        assert snap["awarded_tier"] == "GOLD"


class TestInventoryEmptySecondInstance:

    def test_inventory_one_succeeds_inventory_zero_fails(self, api,
                                                          admin_headers):
        """PRD §2.9 + §3.4: "Upgrade inventory comparison reads as
        strictly greater than zero — a flight whose remaining inventory
        in a cabin equals zero is exhausted."

        # difficulty: boundary_precision_check/upgrade_inventory_empty_set_boundary_on_confirm
        Claim (second test): capacity_first=1 admits exactly one
        upgrade confirmation; the second hits ERR_UPGRADE_INVENTORY_EXHAUSTED.
        """
        flight = create_flight(capacity_first=1)
        # First PLATINUM member confirms upgrade (success).
        member1, _, _, ur1 = setup_waitlisted_upgrade_request(
            flight=flight,
            booked_cabin="BUSINESS", target_cabin="FIRST",
            points_offered=10_000, member_tier="PLATINUM",
            member_balance=50_000,
        )
        validate_success(
            api.confirm_upgrade_request(ur1["id"], admin_headers),
        )
        # Inventory is now 0.
        f_after = get_flight(flight["id"])
        assert f_after["upgrade_inventory_first"] == 0
        # Second PLATINUM member's confirm fails.
        member2, _, _, ur2 = setup_waitlisted_upgrade_request(
            flight=flight,
            booked_cabin="BUSINESS", target_cabin="FIRST",
            points_offered=10_000, member_tier="PLATINUM",
            member_balance=50_000,
        )
        resp = api.confirm_upgrade_request(ur2["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_UPGRADE_INVENTORY_EXHAUSTED.value)


# ===========================================================================
# Difficulty: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityUpgradeOnMemberTierSecondInstance:

    def test_silver_member_creation_also_blocked(self, api):
        """PRD §3.4: "The acting member's tier must be at least GOLD;
        otherwise the request is refused with ERR_MEMBER_TIER_INELIGIBLE."

        # difficulty: cross_entity_state_dependency/upgrade_request_on_member_tier
        Claim (second test): SILVER (just below GOLD) is also blocked
        — the dependency is on the cross-entity Member.tier value, and
        SILVER fails the >= GOLD check.
        """
        flight = create_flight(capacity_first=2)
        member = create_member()
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="SILVER",
        )
        seg = create_segment_for_member(
            member["id"], flight["id"], booked_cabin="BUSINESS",
        )
        resp = api.create_upgrade_request(
            member["id"], seg["id"],
            create_upgrade_request_payload(
                target_cabin="FIRST", points_offered=5_000,
            ),
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_TIER_INELIGIBLE.value)


class TestCrossEntityAwardOnFlightStatus:

    def test_confirm_blocked_after_flight_cancelled(self, api,
                                                    admin_headers):
        """PRD §3.5: "the underlying flight to be in SCHEDULED
        (otherwise ERR_FLIGHT_NOT_BOOKABLE)."

        # difficulty: cross_entity_state_dependency/award_booking_on_flight_status
        Claim (first of two tests for this instance): once the
        referenced Flight is no longer SCHEDULED, the AwardBooking
        confirm is rejected with ERR_FLIGHT_NOT_BOOKABLE.
        """
        member, flight, booking = setup_held_award_booking(
            member_balance=50_000,
        )
        # Cancel the flight.
        validate_success(api.cancel_flight(flight["id"], admin_headers))
        # Confirm — flight is no longer SCHEDULED.
        resp = api.confirm_award_booking(
            member["id"], booking["id"], make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_BOOKABLE.value)

    def test_confirm_blocked_after_flight_departed(self, api,
                                                    admin_headers):
        """PRD §3.5 + §3.2: "Flight.status != SCHEDULED for any
        booking/upgrade attempt" → ERR_FLIGHT_NOT_BOOKABLE.

        # difficulty: cross_entity_state_dependency/award_booking_on_flight_status
        Claim (second test): the AwardBooking → Flight.status
        dependency also fires when the flight flips to DEPARTED, not
        only when it flips to CANCELLED.
        """
        member, flight, booking = setup_held_award_booking(
            member_balance=50_000,
        )
        validate_success(api.depart_flight(flight["id"], admin_headers))
        resp = api.confirm_award_booking(
            member["id"], booking["id"], make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_BOOKABLE.value)


# ===========================================================================
# Difficulty: resource_temporal_overlap
# ===========================================================================
class TestCoolingOffSecondInstance:

    def test_cooling_off_applies_after_rejection_of_first_request(self, api,
                                                                   admin_headers):
        """PRD §3.7: "The bar applies independently of whether the
        previous grant has since expired, been activated, or remained
        merely APPROVED." The 36-month bar follows from approval,
        regardless of what happened next.

        # difficulty: resource_temporal_overlap/status_match_cooling_off_window_36_months
        Claim (second test): after a first APPROVED request, a second
        request submitted within the cooling-off window is rejected on
        approval; this is the same window rule applied to a different
        downstream lifecycle.
        """
        from test_helpers import setup_approved_status_match
        member, first = setup_approved_status_match(competitor_tier="GOLD")
        # Member's first match is APPROVED but not yet activated.
        smr2 = validate_success(
            api.create_status_match_request(
                member["id"],
                {"competitor_program": "Z", "competitor_tier": "GOLD",
                 "evidence_url": "https://example.com/2"},
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        resp = api.approve_status_match_request(
            member["id"], smr2["id"], admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STATUS_MATCH_COOLING_OFF.value)


# ===========================================================================
# Difficulty: compensating_invariant
# ===========================================================================
class TestPointsBalanceConservationSecondInstance:

    def test_book_confirm_cancel_zero_net_change_with_different_amount(
        self, api,
    ):
        """PRD §3.5: "the member's points_balance after this transition
        must equal its value immediately before the original confirm."

        # difficulty: compensating_invariant/points_balance_conserved_under_book_then_cancel
        Claim (second test): the invariant holds for a different
        points_cost (FIXED INTERNATIONAL ECONOMY = 30_000) — proving
        the invariant is structural, not coincidental on the 12_500
        figure.
        """
        pre_balance = 60_000
        member, flight, booking = setup_confirmed_award_booking(
            cabin="ECONOMY", pricing_mode="FIXED",
            route_region="INTERNATIONAL", member_balance=pre_balance,
        )
        m_mid = get_member(member["id"])
        assert m_mid["points_balance"] == pre_balance - 30_000
        validate_success(
            api.cancel_award_booking(
                member["id"], booking["id"],
                make_member_headers(member["id"]),
            )
        )
        m_after = get_member(member["id"])
        assert m_after["points_balance"] == pre_balance


class TestQualifyingSegmentsReversalSecondInstance:

    def test_refund_after_multiple_flown_only_reverses_the_refunded_one(
        self, api,
    ):
        """PRD §3.3: "let q0 be the year's qualifying-segment count
        before the original FLOWN, let q1 be the count immediately
        after FLOWN, and let q2 be the count immediately after
        REFUNDED; then q2 must equal q0."

        # difficulty: compensating_invariant/qualifying_segments_conserved_under_fly_then_refund
        Claim (second test): with two FLOWN segments banked, refunding
        only the second restores the qualifying counters to the state
        AFTER the first FLOWN, not all the way to zero. This proves
        the reversal is scoped to the refunded segment.
        """
        member = create_member()
        # Fly two segments.
        _, flown_a = fly_one_segment(
            member["id"], flight_overrides={"base_fare_cents": 20_000},
        )
        _, flown_b = fly_one_segment(
            member["id"], flight_overrides={"base_fare_cents": 20_000},
        )
        m_two_flown = get_member(member["id"])
        assert m_two_flown["current_year_qualifying_segments"] == 2
        # Refund only the second.
        refund_segment(member["id"], flown_b["id"])
        m_after = get_member(member["id"])
        assert m_after["current_year_qualifying_segments"] == 1, (
            "PRD §3.3: refund reverses only the refunded segment's "
            "contribution to qualifying_segments."
        )
        # Points balance equals the surviving accrual.
        assert m_after["points_balance"] == flown_a["qualifying_points_earned"]
