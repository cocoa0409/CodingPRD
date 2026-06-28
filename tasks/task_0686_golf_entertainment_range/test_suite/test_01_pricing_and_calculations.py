"""Dynamic bay pricing, F&B tab totals, event pricing, deposit waterfall, scoring,
and loyalty-earn calculations.

Each test translates exactly one design-index instance (queue A difficulty or
queue B corner). Literal expected values are copied from the design index.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_guest_headers,
    create_reservation_payload,
    create_venue_payload,
    create_bay_payload,
    create_member_payload,
    fb_item_payload,
    set_clock,
    create_venue,
    create_bay,
    create_member,
    create_member_with_wallet,
    setup_confirmed_reservation,
    setup_session_on_confirmed_reservation,
    setup_walkin_session,
    open_session_tab,
    add_items,
    setup_confirmed_event_with_closed_tab,
)

RM = TEST_USERS["range_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ===========================================================================
# Queue A — combinatorial_formula / dynamic_bay_price_nonlinear_three_input_with_clamp
# ===========================================================================
class TestDynamicBayPriceClamp:
    def test_peak_weekend_clamped_to_ceiling(self, api):
        """PRD §3.3: "The raw multiplier is the band multiplier times the day
        factor times the venue's `peak_demand_factor`. The effective multiplier
        is the raw multiplier clamped to lie no lower than 0.80 and no higher than
        2.00 — that is, the larger of 0.80 and the smaller of 2.00 and the raw
        multiplier. The gross amount is then computed by multiplying the venue's
        `base_rate_cents_per_half_hour` by the number of segments and by the
        effective multiplier as a single product, rounded half up to whole cents
        exactly once (the rounding is applied to the whole product, never per
        segment)."

        PEAK(1.60) * WEEKEND(1.25) * 1.0 = 2.00 (at ceiling); gross =
        round(2500*2*2.00)=10000; STANDARD discount 0 -> quoted 10000.

        Design: Difficulty/combinatorial_formula/dynamic_bay_price_nonlinear_three_input_with_clamp
        """
        venue = create_venue(base_rate_cents_per_half_hour=2500, peak_demand_factor=1.0)
        bay = create_bay(venue["id"])
        member = create_member(tier="STANDARD")
        payload = create_reservation_payload(
            venue["id"], bay["id"], member["id"],
            "2026-06-06T18:00:00Z", "2026-06-06T19:00:00Z", "PEAK",
            day_type="WEEKEND")
        res = validate_success(
            api.create_reservation(payload, make_guest_headers(member["id"])), 201)
        assert res["quoted_price_cents"] == 10000, \
            f"PEAK*WEEKEND clamped to 2.00 ceiling => 10000, got {res['quoted_price_cents']}"

    def test_peak_demand_factor_pushes_raw_above_ceiling_still_clamped(self, api):
        """PRD §3.3: "The raw multiplier is the band multiplier times the day
        factor times the venue's `peak_demand_factor`. The effective multiplier
        is the raw multiplier clamped to lie no lower than 0.80 and no higher than
        2.00 — that is, the larger of 0.80 and the smaller of 2.00 and the raw
        multiplier. The gross amount is then computed by multiplying the venue's
        `base_rate_cents_per_half_hour` by the number of segments and by the
        effective multiplier as a single product, rounded half up to whole cents
        exactly once (the rounding is applied to the whole product, never per
        segment)."

        The third input drives the clamp: PEAK(1.60)*WEEKEND(1.25)*1.5 = 3.0 raw,
        which clamps DOWN to the 2.00 ceiling; gross = round(2500*2*2.00)=10000;
        STANDARD discount 0 -> quoted 10000 (same as the at-ceiling case, proving the
        ceiling is honored when peak_demand_factor pushes the raw multiplier over it).

        Design: Difficulty/combinatorial_formula/dynamic_bay_price_nonlinear_three_input_with_clamp
        """
        venue = create_venue(base_rate_cents_per_half_hour=2500, peak_demand_factor=1.5)
        bay = create_bay(venue["id"])
        member = create_member(tier="STANDARD")
        payload = create_reservation_payload(
            venue["id"], bay["id"], member["id"],
            "2026-06-06T18:00:00Z", "2026-06-06T19:00:00Z", "PEAK",
            day_type="WEEKEND")
        res = validate_success(
            api.create_reservation(payload, make_guest_headers(member["id"])), 201)
        assert res["quoted_price_cents"] == 10000, \
            f"raw 3.0 clamped to 2.00 ceiling => 10000, got {res['quoted_price_cents']}"

    def test_twilight_platinum_discount_applied(self, api):
        """PRD §3.3: "A band multiplier is selected by `time_band`: 0.80 for
        `TWILIGHT`, 1.00 for `OFFPEAK`, and 1.60 for `PEAK`. A day factor is
        selected by `day_type`: 1.00 for `WEEKDAY` and 1.25 for `WEEKEND`."
        PRD §3.3: "A discount percentage is selected by the member's `tier`: 0.00
        for `STANDARD`, 0.10 for `GOLD`, and 0.15 for `PLATINUM`. The discount
        amount is the gross times the discount percentage, rounded half up to whole
        cents. The `quoted_price_cents` is the gross minus the discount and is never
        negative."

        TWILIGHT(0.80)*WEEKDAY(1.00) on 90-min base 2500 => gross 6000; PLATINUM
        0.15 discount 900 -> quoted 5100.

        Design: Corner/calculations/bay_price_twilight_platinum_discount_applied
        """
        venue = create_venue(base_rate_cents_per_half_hour=2500)
        bay = create_bay(venue["id"])
        member = create_member(tier="PLATINUM")
        payload = create_reservation_payload(
            venue["id"], bay["id"], member["id"],
            "2026-06-02T07:00:00Z", "2026-06-02T08:30:00Z", "TWILIGHT",
            day_type="WEEKDAY")
        res = validate_success(
            api.create_reservation(payload, make_guest_headers(member["id"])), 201)
        assert res["quoted_price_cents"] == 5100, \
            f"TWILIGHT*WEEKDAY 90-min PLATINUM => 5100, got {res['quoted_price_cents']}"

    def test_round_total_order_diverges_from_per_segment(self, api):
        """PRD §3.3: "The gross amount is then computed by multiplying the venue's
        `base_rate_cents_per_half_hour` by the number of segments and by the
        effective multiplier as a single product, rounded half up to whole cents
        exactly once (the rounding is applied to the whole product, never per
        segment)."

        base 2495, OFFPEAK(1.00)*WEEKEND(1.25) on 90 min => round(2495*3*1.25)=
        round(9356.25)=9356 (NOT per-segment 9357).

        Design: Corner/calculations/bay_price_round_total_order_diverges_from_per_segment
        """
        venue = create_venue(base_rate_cents_per_half_hour=2495)
        bay = create_bay(venue["id"])
        member = create_member(tier="STANDARD")
        payload = create_reservation_payload(
            venue["id"], bay["id"], member["id"],
            "2026-06-06T18:00:00Z", "2026-06-06T19:30:00Z", "OFFPEAK",
            day_type="WEEKEND")
        res = validate_success(
            api.create_reservation(payload, make_guest_headers(member["id"])), 201)
        assert res["quoted_price_cents"] == 9356, \
            f"ROUND_TOTAL once => 9356, got {res['quoted_price_cents']}"


# ===========================================================================
# Queue A — combinatorial_formula / fb_tab_total_nested_rounding_order_gratuity_before_tax
# ===========================================================================
class TestFbTabNestedRounding:
    def _open_tab_with_items(self, api, items):
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member()
        session = get_success_data(api.create_session(
            {"bay_id": bay["id"], "member_id": member["id"]}, FD))
        tab = get_success_data(api.create_fb_tab({"session_id": session["id"]}, FD))
        last = tab
        for name, price, qty in items:
            last = validate_success(
                api.add_fb_item(tab["id"], fb_item_payload(name, price, qty), FD), 200)
        return last

    def test_gratuity_rounded_before_tax(self, api):
        """PRD §3.9: "The `gratuity_cents` is an auto-gratuity of 18 percent of the
        subtotal, rounded half up to whole cents on the full subtotal (not per line
        item). The `tax_cents` is 8.25 percent of the sum of the subtotal and the
        already-rounded gratuity, rounded half up to whole cents — tax is computed
        on the subtotal-plus-gratuity, and the gratuity is rounded before the tax is
        computed. The `total_cents` is the sum of `subtotal_cents`,
        `gratuity_cents`, and `tax_cents`."

        Items 1299, 1850, 950 => subtotal 4099; gratuity round(4099*0.18)=738;
        tax round((4099+738)*0.0825)=399; total 5236.

        Design: Difficulty/combinatorial_formula/fb_tab_total_nested_rounding_order_gratuity_before_tax
        """
        tab = self._open_tab_with_items(
            api, [("Burger", 1299, 1), ("Bottle", 1850, 1), ("Fries", 950, 1)])
        assert tab["subtotal_cents"] == 4099
        assert tab["gratuity_cents"] == 738
        assert tab["tax_cents"] == 399
        assert tab["total_cents"] == 5236

    def test_total_equals_sum_of_components(self, api):
        """PRD §3.9: "The `total_cents` is the sum of `subtotal_cents`,
        `gratuity_cents`, and `tax_cents`."

        Same 1299/1850/950 tab — verify total decomposes into its three rounded
        components (5236 = 4099 + 738 + 399).

        Design: Difficulty/combinatorial_formula/fb_tab_total_nested_rounding_order_gratuity_before_tax
        """
        tab = self._open_tab_with_items(
            api, [("Burger", 1299, 1), ("Bottle", 1850, 1), ("Fries", 950, 1)])
        assert tab["total_cents"] == (
            tab["subtotal_cents"] + tab["gratuity_cents"] + tab["tax_cents"])
        assert tab["total_cents"] == 5236


# ===========================================================================
# Queue A — dual_variant_calc / event_pricing_provisional_vs_settled_diverges
# ===========================================================================
class TestEventPricingDualVariant:
    def test_provisional_and_settled_totals_diverge(self, api):
        """PRD §3.10: "On creation the package is `QUOTED` and its
        `estimated_total_cents` is computed by the provisional pricing variant: the
        `headcount_estimate` times `per_head_package_cents`, plus `bay_block_cents`."
        PRD §3.10: "Settlement records `actual_attendee_count` and computes
        `final_total_cents` by the settled pricing variant: the
        `actual_attendee_count` times `per_head_package_cents`, plus
        `bay_block_cents`, plus the sum of `total_cents` over all closed F&B tabs for
        the event."

        est = 20*6500 + 15000 = 145000. The closed catering tab's total_cents is
        the subtotal-plus-gratuity-plus-tax of an 8200 line item: 8200 + 1476 + 798
        = 10474 (PRD §3.9). final = 17*6500 + 15000 + 10474 = 135974.

        Design: Difficulty/dual_variant_calc/event_pricing_provisional_vs_settled_diverges_on_event_package
        """
        set_clock("2026-06-01T12:00:00Z")
        venue, organizer, event, tab = setup_confirmed_event_with_closed_tab(
            catering_cents=8200, headcount_estimate=20, per_head_package_cents=6500,
            bay_block_cents=15000, deposit_cents=140000, wallet_cents=200000)
        assert event["estimated_total_cents"] == 145000
        settled = validate_success(
            api.settle_event_package(event["id"], {"actual_attendee_count": 17}, RM), 200)
        assert settled["final_total_cents"] == 135974
        assert settled["estimated_total_cents"] != settled["final_total_cents"]

    def test_estimated_total_provisional_formula(self, api):
        """PRD §3.10: "On creation the package is `QUOTED` and its
        `estimated_total_cents` is computed by the provisional pricing variant: the
        `headcount_estimate` times `per_head_package_cents`, plus `bay_block_cents`."

        est = 20*6500 + 15000 = 145000 at QUOTED creation, independent of the later
        settled count.

        Design: Difficulty/dual_variant_calc/event_pricing_provisional_vs_settled_diverges_on_event_package
        """
        from test_helpers import create_quoted_event
        venue = create_venue(bay_count=4)
        organizer = create_member()
        event = create_quoted_event(
            venue["id"], organizer["id"], 20, 6500,
            bay_block_cents=15000, deposit_cents=0)
        assert event["status"] == "QUOTED"
        assert event["estimated_total_cents"] == 145000


# ===========================================================================
# Queue B — calculations / deposit_waterfall_overflow_refunds_remainder
# ===========================================================================
def test_deposit_waterfall_overflow_refunds_remainder(api):
    """PRD §3.10: "The held deposit is then applied by the deposit waterfall:
    starting from `deposit_cents` as the remaining amount, three buckets are filled
    in this fixed order — first the `bay_block_cents`, then the per-head amount
    (`actual_attendee_count` times `per_head_package_cents`), then the event F&B
    total — and for each bucket in turn the amount applied is the smaller of the
    remaining deposit and the bucket's value, with that applied amount subtracted
    from the remaining. The deposit actually applied is `deposit_cents` minus
    whatever remains after the three buckets, and that leftover remainder becomes
    `deposit_refund_cents`. The server creates a charge of kind `EVENT_SETTLEMENT`
    for the organizer whose amount is `final_total_cents` minus the deposit applied,
    credits the organizer's `wallet_balance_cents` by `deposit_refund_cents`, moves
    the package to `SETTLED`, and increments the package's `version` by 1."

    The closed catering tab's total_cents is 8200 + 1476 + 798 = 10474 (PRD §3.9).
    deposit 140000 over buckets [15000, 110500, 10474] fully fills all three
    (135974 applied); refund 140000-135974 = 4026; organizer wallet
    200000-140000+4026 = 64026.

    Design: Corner/calculations/deposit_waterfall_overflow_refunds_remainder
    """
    set_clock("2026-06-01T12:00:00Z")
    venue, organizer, event, tab = setup_confirmed_event_with_closed_tab(
        catering_cents=8200, headcount_estimate=20, per_head_package_cents=6500,
        bay_block_cents=15000, deposit_cents=140000, wallet_cents=200000)
    settled = validate_success(
        api.settle_event_package(event["id"], {"actual_attendee_count": 17}, RM), 200)
    assert settled["deposit_refund_cents"] == 4026
    organizer_after = validate_success(api.get_member(organizer["id"], RM), 200)
    assert organizer_after["wallet_balance_cents"] == 64026


# ===========================================================================
# Queue A — boundary_precision_check / scoring_streak_run_of_exactly_five_awards_bonus
# ===========================================================================
class TestScoringStreakBoundary:
    def _start_session(self, api):
        venue = create_venue()
        bay = create_bay(venue["id"])
        member = create_member()
        return get_success_data(api.create_session(
            {"bay_id": bay["id"], "member_id": member["id"]}, FD))

    def test_run_of_exactly_five_awards_bonus(self, api):
        """PRD §3.6: "A one-time streak bonus of 25 points is awarded if, and only
        if, there exists anywhere in the shot sequence (in `seq` order) a run of at
        least 5 consecutive shots each scoring at least 10 points; the bonus is added
        at most once per session regardless of how many qualifying runs occur. The
        `total_score` is the base plus the bonus, and `shot_count` is the number of
        shots recorded."

        Five shots 10,11,12,13,14 (each >=10) => run of exactly 5 => +25 bonus;
        base 60 + 25 = 85; shot_count 5.

        Design: Difficulty/boundary_precision_check/scoring_streak_run_of_exactly_five_awards_bonus
        """
        session = self._start_session(api)
        for pts in (10, 11, 12, 13):
            validate_success(api.record_shot(session["id"], {"points": pts}, FD), 200)
        final = validate_success(
            api.record_shot(session["id"], {"points": 14}, FD), 200)
        assert final["shot_count"] == 5
        assert final["total_score"] == 85

    def test_run_of_four_no_bonus(self, api):
        """PRD §3.6: "A one-time streak bonus of 25 points is awarded if, and only
        if, there exists anywhere in the shot sequence (in `seq` order) a run of at
        least 5 consecutive shots each scoring at least 10 points; the bonus is added
        at most once per session regardless of how many qualifying runs occur. The
        `total_score` is the base plus the bonus, and `shot_count` is the number of
        shots recorded."

        Four shots 10,11,12,13 (run length 4 < 5) => no bonus; base 46, no +25;
        boundary one below the threshold of the exact-five case.

        Design: Difficulty/boundary_precision_check/scoring_streak_run_of_exactly_five_awards_bonus
        """
        session = self._start_session(api)
        for pts in (10, 11, 12):
            validate_success(api.record_shot(session["id"], {"points": pts}, FD), 200)
        final = validate_success(
            api.record_shot(session["id"], {"points": 13}, FD), 200)
        assert final["shot_count"] == 4
        assert final["total_score"] == 46


# ===========================================================================
# Queue B — calculations / scoring_empty_session_total_is_zero
# ===========================================================================
def test_scoring_empty_session_total_is_zero(api):
    """PRD §3.6: "The base score is the sum of the `points` of all recorded shots."
    PRD §3.6: "The `total_score` is the base plus the bonus, and `shot_count` is the
    number of shots recorded."

    A session with zero shots has total_score 0 and shot_count 0 (empty-set edge).

    Design: Corner/calculations/scoring_empty_session_total_is_zero
    """
    venue = create_venue()
    bay = create_bay(venue["id"])
    member = create_member()
    session = get_success_data(api.create_session(
        {"bay_id": bay["id"], "member_id": member["id"]}, FD))
    fetched = validate_success(api.get_session(session["id"], FD), 200)
    assert fetched["total_score"] == 0
    assert fetched["shot_count"] == 0


# ===========================================================================
# Queue A — dual_variant_calc / loyalty_earn_provisional_vs_final_diverges_on_member
# ===========================================================================
class TestLoyaltyEarnDualVariant:
    def test_provisional_at_confirm_then_final_at_session_end(self, api):
        """PRD §3.7: "The provisional earn on a net amount in cents is that amount
        divided by 100, floored — one point per whole 100 cents, independent of tier
        — and is what accrues to `pending_loyalty_points` at charge time; it is fully
        reversible. The final earn applies the member's tier multiplier before
        flooring: it is the net cents divided by 100, multiplied by the tier
        multiplier, then floored, where the tier multiplier is 1.0 for `STANDARD`,
        1.25 for `GOLD`, and 1.5 for `PLATINUM`. The final earn is what lands in
        `loyalty_points` when a session ends, at which point the matching provisional
        accrual is cleared from `pending_loyalty_points`."

        net quote 6800 => provisional floor(6800/100)=68 at confirm; at session end
        PLATINUM x1.5 => floor(68*1.5)=102 confirmed; pending cleared to 0.

        Design: Difficulty/dual_variant_calc/loyalty_earn_provisional_vs_final_diverges_on_member
        """
        set_clock("2026-06-01T12:00:00Z")
        venue, bay, member, res, session = setup_session_on_confirmed_reservation(
            clock=None, tier="PLATINUM", wallet_cents=50000, base_rate_cents=2500)
        assert res["quoted_price_cents"] == 6800
        validate_success(api.end_session(session["id"], FD), 200)
        member_after = validate_success(api.get_member(member["id"], RM), 200)
        assert member_after["pending_loyalty_points"] == 0
        assert member_after["loyalty_points"] == 102

    def test_provisional_accrues_at_confirm_before_end(self, api):
        """PRD §3.4: "Provisional loyalty is accrued on this charge: the member's
        `pending_loyalty_points` is increased by the provisional earn on
        `quoted_price_cents`."
        PRD §3.7: "The provisional earn on a net amount in cents is that amount
        divided by 100, floored — one point per whole 100 cents, independent of tier
        — and is what accrues to `pending_loyalty_points` at charge time; it is fully
        reversible."

        After WALLET confirm of a 6800 quote, pending_loyalty_points == 68 and
        confirmed loyalty_points is still 0 (final not yet earned).

        Design: Difficulty/dual_variant_calc/loyalty_earn_provisional_vs_final_diverges_on_member
        """
        set_clock("2026-06-01T12:00:00Z")
        venue, bay, member, res = setup_confirmed_reservation(
            clock=None, tier="PLATINUM", wallet_cents=50000, base_rate_cents=2500)
        assert res["quoted_price_cents"] == 6800
        member_after = validate_success(api.get_member(member["id"], RM), 200)
        assert member_after["pending_loyalty_points"] == 68
        assert member_after["loyalty_points"] == 0
