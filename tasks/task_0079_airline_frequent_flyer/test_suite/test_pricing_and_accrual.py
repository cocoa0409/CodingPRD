"""Queue A (Difficulty) — award pricing and segment-accrual calculations.

Covers dual_variant_calc and combinatorial_formula instances.
"""
from test_helpers import validate_success
from test_helpers.fixtures import (
    set_clock, create_member, member_headers_for, grant_status_match,
    create_companion_certificate, create_flown_segment, accrue_segment, quote_award,
)
from test_helpers.factories import create_award_booking_payload


class TestAwardPricingDynamicVsFixed:
    """Design rule dual_variant_calc / award_pricing_dynamic_vs_fixed."""

    def test_dynamic_business_load_factor_half(self, api):
        """PRD §3.5: "Under DYNAMIC pricing the cabin price scales with live demand:
        the chart value is multiplied by the quantity zero-point-eight plus
        zero-point-eight times the load_factor, then rounded half-up - so the
        multiplier ranges from 0.8 at a load factor of 0 to 1.6 at a load factor of
        1, and a load factor of 0.5 yields 1.2 times the chart, diverging from the
        fixed price for the same route and cabin."

        Design: Difficulty/dual_variant_calc/award_pricing_dynamic_vs_fixed
        """
        set_clock(api, "2026-01-10T00:00:00.000Z")
        m = create_member(api)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="BUSINESS", pricing_mode="DYNAMIC", load_factor=0.5),
                member_headers_for(m),
            ),
            201,
        )
        assert award["points_price"] == 72000, award  # 60000*(0.8+0.8*0.5)=60000*1.2

    def test_fixed_business_equals_chart(self, api):
        """PRD §3.5: "Under FIXED pricing the cabin price is exactly that chart value,
        independent of demand."
        PRD §3.5: "A base chart price is read for the cabin: ECONOMY is 25000, BUSINESS
        is 60000, and FIRST is 100000 points."

        Design: Difficulty/dual_variant_calc/award_pricing_dynamic_vs_fixed
        """
        set_clock(api, "2026-01-10T00:00:00.000Z")
        m = create_member(api)
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(m["id"], cabin="BUSINESS", pricing_mode="FIXED"),
                member_headers_for(m),
            ),
            201,
        )
        assert award["points_price"] == 60000, award


class TestSegmentAccrualFloorVsFare:
    """Design rule dual_variant_calc / segment_accrual_floor_vs_fare."""

    def test_floor_dominates_cheap_long_haul(self, api):
        """PRD §3.2: "Independently, a distance-based floor is computed by multiplying
        distance_miles by the minimum mile rate of 0.5 points per mile and rounding
        that product up to the next whole number."
        PRD §3.2: "The segment's pre-bonus earning is the larger of the fare-based
        figure and the distance-based floor - so a cheap long-haul still earns its
        mile-based minimum, while an expensive short-haul earns on spend."

        Design: Difficulty/dual_variant_calc/segment_accrual_floor_vs_fare
        """
        m = create_member(api)
        seg = create_flown_segment(
            api, m["id"], "2026-01-10T00:00:00.000Z",
            origin="SFO", destination="JFK", fare_class="ECONOMY",
            distance_miles=2580, base_fare_usd=100, scheduled_departure="2026-01-05T08:00:00.000Z",
        )
        accrued = accrue_segment(api, seg["id"])
        # base=100*1.0=100; floor=ceil(2580*0.5)=1290; max=1290; BASE bonus 0%
        assert accrued["points_awarded"] == 1290, accrued

    def test_fare_dominates_expensive_short_haul(self, api):
        """PRD §3.2: "A fare-based figure is the paid base_fare_usd multiplied by that
        class multiplier."
        PRD §3.2: "The segment's pre-bonus earning is the larger of the fare-based
        figure and the distance-based floor - so a cheap long-haul still earns its
        mile-based minimum, while an expensive short-haul earns on spend."

        Design: Difficulty/dual_variant_calc/segment_accrual_floor_vs_fare
        """
        m = create_member(api)
        seg = create_flown_segment(
            api, m["id"], "2026-01-10T00:00:00.000Z",
            origin="SFO", destination="LAX", fare_class="ECONOMY",
            distance_miles=340, base_fare_usd=800, scheduled_departure="2026-01-05T08:00:00.000Z",
        )
        accrued = accrue_segment(api, seg["id"])
        # base=800*1.0=800; floor=ceil(340*0.5)=170; max=800; BASE bonus 0%
        assert accrued["points_awarded"] == 800, accrued


class TestSegmentAccrualNonlinearWithTierBonus:
    """Design rule combinatorial_formula / segment_accrual_mode_a_nonlinear."""

    def test_business_segment_with_gold_match_bonus(self, api):
        """PRD §3.2: "A tier bonus percentage is then selected from the member's
        effective tier at the accrual instant: 0 for BASE, 25 for SILVER, 50 for GOLD,
        and 100 for PLATINUM."
        PRD §3.3: "a rival_tier of SILVER yields a matched tier of BASE, GOLD yields
        SILVER, and PLATINUM yields GOLD."

        Design: Difficulty/combinatorial_formula/segment_accrual_mode_a_nonlinear
        """
        set_clock(api, "2026-02-01T00:00:00.000Z")
        m = create_member(api)
        grant_status_match(api, m["id"], rival_tier="PLATINUM")  # matched_tier GOLD -> bonus 50%
        seg = create_flown_segment(
            api, m["id"], "2026-02-01T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="BUSINESS",
            distance_miles=340, base_fare_usd=800, scheduled_departure="2026-01-20T08:00:00.000Z",
        )
        accrued = accrue_segment(api, seg["id"])
        # base=800*1.5=1200; floor=ceil(340*0.5)=170; max=1200; GOLD bonus 50% -> 1800
        assert accrued["points_awarded"] == 1800, accrued

    def test_first_segment_platinum_match_doubles(self, api):
        """PRD §3.2: "The final points_awarded is the pre-bonus earning multiplied by
        one plus that bonus percentage expressed as a fraction (so a 25 percent bonus
        multiplies by 1.25, and a 100 percent bonus doubles it), with the result
        rounded half-up to a whole number of points."
        PRD §3.2: "First, a class multiplier is selected from the fare class: 0.5 for
        DISCOUNT, 1.0 for ECONOMY, 1.5 for BUSINESS, and 2.0 for FIRST."

        Design: Difficulty/combinatorial_formula/segment_accrual_mode_a_nonlinear
        """
        set_clock(api, "2026-02-01T00:00:00.000Z")
        m = create_member(api)
        grant_status_match(api, m["id"], rival_tier="PLATINUM")  # matched_tier GOLD -> 50%
        seg = create_flown_segment(
            api, m["id"], "2026-02-01T00:00:01.000Z",
            origin="SFO", destination="LAX", fare_class="FIRST",
            distance_miles=340, base_fare_usd=1000, scheduled_departure="2026-01-25T08:00:00.000Z",
        )
        accrued = accrue_segment(api, seg["id"])
        # base=1000*2.0=2000; floor=170; max=2000; GOLD bonus 50% -> 3000
        assert accrued["points_awarded"] == 3000, accrued


class TestAwardCompanionRoundingOrder:
    """Design rule combinatorial_formula / award_pricing_companion_rounding_order."""

    def test_dynamic_economy_with_companion_addon(self, api):
        """PRD §3.5: "If a companion certificate is attached, a companion add-on equal
        to 50 percent of the cabin price (rounded half-up) is added; otherwise the
        add-on is zero."
        PRD §3.5: "The pinned points_price is the cabin price plus the companion
        add-on."

        Design: Difficulty/combinatorial_formula/award_pricing_companion_rounding_order
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(
                    m["id"], cabin="ECONOMY", pricing_mode="DYNAMIC",
                    load_factor=0.625, companion_certificate_id=cert["id"],
                ),
                member_headers_for(m),
            ),
            201,
        )
        # cabin_price=round_half_up(25000*(0.8+0.8*0.625))=round_half_up(25000*1.3)=32500
        # companion_addon=round_half_up(32500*0.5)=16250; total=48750
        assert award["points_price"] == 48750, award

    def test_fixed_first_with_companion_addon(self, api):
        """PRD §3.5: "If a companion certificate is attached, a companion add-on equal
        to 50 percent of the cabin price (rounded half-up) is added; otherwise the
        add-on is zero."
        PRD §3.5: "Under FIXED pricing the cabin price is exactly that chart value,
        independent of demand."

        Design: Difficulty/combinatorial_formula/award_pricing_companion_rounding_order
        """
        set_clock(api, "2026-03-01T00:00:00.000Z")
        m = create_member(api)
        cert = create_companion_certificate(
            api, m["id"], valid_from="2026-01-01T00:00:00.000Z", valid_until="2026-12-31T00:00:00.000Z"
        )
        award = validate_success(
            api.create_award_booking(
                create_award_booking_payload(
                    m["id"], cabin="FIRST", pricing_mode="FIXED", companion_certificate_id=cert["id"],
                ),
                member_headers_for(m),
            ),
            201,
        )
        # cabin_price=100000 (FIXED FIRST); addon=round_half_up(100000*0.5)=50000; total=150000
        assert award["points_price"] == 150000, award
