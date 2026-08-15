"""Flight pricing math, volume discounts, and the impressions book."""
from test_helpers import (
    IM,
    SP,
    api_client,
    append_impression_entry,
    confirm_flight,
    create_advertiser,
    create_campaign,
    create_face_with_permit,
    create_published_rate_card,
    get_success_data,
    hold_flight,
    setup_held_flight,
    setup_live_flight,
    submit_and_approve_campaign,
    validate_success,
)


def _three_static_faces(card_id):
    """F-HI (illuminated, 300000), F-T1 (not lit, 150000), F-LO (not lit, 50000)."""
    faces = {}
    for code, lit, traffic in (
        ("F-HI", True, 300_000), ("F-T1", False, 150_000), ("F-LO", False, 50_000),
    ):
        face, _permit = create_face_with_permit(
            face_code=code, illuminated=lit, daily_traffic_count=traffic,
            permit_number=f"P-{code}",
        )
        faces[code] = face
    return faces


class TestGrossCostTieredMultipliers:

    def test_tier2_and_illumination_multipliers_stack(self):
        """PRD section 3.5: "The weekly price starts from the card's
        `base_weekly_cents`, applies the traffic multiplier — the tier-2 uplift
        `traffic_tier_2_uplift_pct` when the face's `daily_traffic_count` is at
        least `traffic_tier_2_threshold`, otherwise the tier-1 uplift
        `traffic_tier_1_uplift_pct` when it is at least
        `traffic_tier_1_threshold`, otherwise no uplift — then applies the
        illumination premium (one plus `illumination_premium_pct`) when the
        face is `illuminated`, and finally, for a `DIGITAL` face, the slot
        share (`loop_slots` divided by `loop_slots_total`). The result is
        rounded half-up to whole cents, once, yielding `pinned_weekly_cents`;
        multiplying by `weeks` yields `gross_cents`."
        PRD section 3.5: "The billed length `weeks` is the inclusive day count
        of the flight divided by seven and rounded up — a partial week bills
        as a full week."

        Design: Difficulty/combinatorial_formula/flight_gross_cost_tiered_multipliers
        """
        card = create_published_rate_card()
        faces = _three_static_faces(card["id"])
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])

        flight = hold_flight(campaign["id"], faces["F-HI"]["id"], card["id"])
        assert flight["pinned_weekly_cents"] == 287_500, (
            f"tier-2 (x1.25) and illumination (x1.15) must stack on base "
            f"200000: expected 287500, got {flight['pinned_weekly_cents']}"
        )
        assert flight["weeks"] == 4, "2026-08-10..2026-09-06 inclusive is 28 days"
        assert flight["gross_cents"] == 1_150_000

    def test_tier1_and_base_branch_selection(self):
        """PRD section 3.5: "The weekly price starts from the card's
        `base_weekly_cents`, applies the traffic multiplier — the tier-2 uplift
        `traffic_tier_2_uplift_pct` when the face's `daily_traffic_count` is at
        least `traffic_tier_2_threshold`, otherwise the tier-1 uplift
        `traffic_tier_1_uplift_pct` when it is at least
        `traffic_tier_1_threshold`, otherwise no uplift — then applies the
        illumination premium (one plus `illumination_premium_pct`) when the
        face is `illuminated`, and finally, for a `DIGITAL` face, the slot
        share (`loop_slots` divided by `loop_slots_total`)."

        Design: Difficulty/combinatorial_formula/flight_gross_cost_tiered_multipliers
        """
        card = create_published_rate_card()
        faces = _three_static_faces(card["id"])
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])

        fl_t1 = hold_flight(campaign["id"], faces["F-T1"]["id"], card["id"])
        assert fl_t1["pinned_weekly_cents"] == 220_000, (
            f"150000 traffic selects the tier-1 branch only: expected 220000, "
            f"got {fl_t1['pinned_weekly_cents']}"
        )
        assert fl_t1["gross_cents"] == 880_000

        fl_lo = hold_flight(campaign["id"], faces["F-LO"]["id"], card["id"])
        assert fl_lo["pinned_weekly_cents"] == 200_000, (
            f"50000 traffic and no illumination selects the base branch: "
            f"expected 200000, got {fl_lo['pinned_weekly_cents']}"
        )
        assert fl_lo["gross_cents"] == 800_000


def _three_digital_flights_for_discount():
    """Card (NYC/DIGITAL, base 625000); three 8-slot digital faces; campaign
    2026-08-01..2026-10-31 APPROVED with one HELD 5-week 4-slot flight each."""
    card = create_published_rate_card(
        display_type="DIGITAL", base_weekly_cents=625_000)
    advertiser = create_advertiser()
    campaign = create_campaign(advertiser["id"], start_date="2026-08-01",
                               end_date="2026-10-31")
    flights = []
    for code in ("F-D1", "F-D2", "F-D3"):
        face, _permit = create_face_with_permit(
            face_code=code, display_type="DIGITAL", illuminated=True,
            daily_traffic_count=300_000, loop_slots_total=8,
            permit_number=f"P-{code}",
        )
        flights.append(hold_flight(
            campaign["id"], face["id"], card["id"],
            start_date="2026-08-10", end_date="2026-09-13", loop_slots=4,
        ))
    submit_and_approve_campaign(campaign["id"])
    return campaign, flights


class TestVolumeDiscountRounding:

    def test_confirm_locks_tier_per_flight_at_crossing(self):
        """PRD section 3.5: "Third, the tier is read off that total: 0.10 —
        ten percent — when the prospective total is at least 15,000,000 cents
        (a $150,000 book); otherwise 0.05 — five percent — when it is at least
        5,000,000 cents ($50,000); otherwise no discount. Fourth, this
        flight's `discount_pct` locks to that tier, immutably. Fifth, this
        flight's `net_cents` finalizes as `gross_cents` plus
        `holdover_charge_cents`, reduced by the locked discount, rounded
        half-up to whole cents — holdover charges are zero at confirm time,
        but the same per-flight formula applies to them when they accrue."

        Design: Difficulty/combinatorial_formula/volume_discount_round_per_flight_then_sum
        """
        campaign, flights = _three_digital_flights_for_discount()
        for fl in flights:
            assert fl["gross_cents"] == 2_246_095, (
                f"weekly 449219 = round_half_up(898437.5 x 4/8), 5 weeks: "
                f"expected gross 2246095, got {fl['gross_cents']}"
            )

        f1 = confirm_flight(flights[0]["id"], campaign["id"])
        assert f1["discount_pct"] == 0 and f1["net_cents"] == 2_246_095, (
            f"prospective total 2246095 stays under the 5000000 floor: "
            f"got discount {f1['discount_pct']}, net {f1['net_cents']}"
        )
        f2 = confirm_flight(flights[1]["id"], campaign["id"])
        assert f2["discount_pct"] == 0 and f2["net_cents"] == 2_246_095, (
            f"prospective total 4492190 stays under the 5000000 floor: "
            f"got discount {f2['discount_pct']}, net {f2['net_cents']}"
        )
        f3 = confirm_flight(flights[2]["id"], campaign["id"])
        assert f3["discount_pct"] == 0.05, (
            f"prospective total 6738285 crosses the 5000000 floor: "
            f"expected locked tier 0.05, got {f3['discount_pct']}"
        )
        assert f3["net_cents"] == 2_133_790, (
            f"round_half_up(2246095 x 0.95): expected 2133790, "
            f"got {f3['net_cents']}"
        )

    def test_campaign_net_is_per_flight_round_then_sum(self):
        """PRD section 3.5: "Sixth, the campaign's `contracted_cents` becomes
        the prospective total, its `discount_pct` becomes this latest tier, and
        its `net_contracted_cents` is the sum of the per-flight net amounts,
        each rounded per flight before summing."
        PRD section 2.6: "Two rounding-order rules are contractual: weekly
        rates are rounded once per week and only then multiplied by the number
        of weeks, and campaign-level net totals are rounded per flight and
        then summed — never the other way around, because the alternative
        order produces different cents."

        Design: Difficulty/combinatorial_formula/volume_discount_round_per_flight_then_sum
        """
        campaign, flights = _three_digital_flights_for_discount()
        for fl in flights:
            confirm_flight(fl["id"], campaign["id"])

        final = validate_success(api_client.get_campaign(campaign["id"], SP), 200)
        assert final["contracted_cents"] == 6_738_285, (
            f"sum of three gross 2246095: expected 6738285, "
            f"got {final['contracted_cents']}"
        )
        # Per-flight locked tiers (0, 0, 0.05) with per-flight rounding:
        # 2246095 + 2246095 + 2133790 = 6625980. Applying the latest tier to
        # every flight (6401370) or tiering the grand total once (6401371)
        # are both ruled out by the pinned evaluation order.
        assert final["net_contracted_cents"] == 6_625_980, (
            f"net totals are rounded per flight with each flight's locked "
            f"tier, then summed: expected 6625980, "
            f"got {final['net_contracted_cents']}"
        )
        assert final["discount_pct"] == 0.05


class TestWeeklyRoundingDigital:

    def test_weekly_rounding_half_up_digital(self):
        """PRD section 3.5: "The result is rounded half-up to whole cents,
        once, yielding `pinned_weekly_cents`; multiplying by `weeks` yields
        `gross_cents`."
        PRD section 2.6: "Whenever a computation produces a fractional cent
        value, the result is rounded half-up to the nearest whole cent."

        Design: Corner/calculations/weekly_rounding_half_up_digital
        """
        card = create_published_rate_card(
            display_type="DIGITAL", base_weekly_cents=625_000)
        face, _permit = create_face_with_permit(
            face_code="F-DIGI-9", display_type="DIGITAL", illuminated=True,
            daily_traffic_count=300_000, loop_slots_total=8,
            permit_number="P-D9",
        )
        advertiser = create_advertiser()
        campaign = create_campaign(advertiser["id"])

        flight = hold_flight(campaign["id"], face["id"], card["id"], loop_slots=1)
        assert flight["pinned_weekly_cents"] == 112_305, (
            f"898437.5 x 1/8 = 112304.6875 rounds half-up once per week to "
            f"112305, got {flight['pinned_weekly_cents']}"
        )
        assert flight["weeks"] == 4
        assert flight["gross_cents"] == 449_220, (
            f"gross is the rounded weekly times weeks (112305 x 4), "
            f"not round(449218.75); got {flight['gross_cents']}"
        )


class TestImpressionsBook:

    def test_measured_entry_replaces_estimate_for_its_period(self):
        """PRD section 3.8: "Within each period, measured evidence wins: if
        any entry in the period has source `AUDIENCE_MEASURED`, the period's
        value is the sum of those measured entries only; otherwise the period
        takes the `TRAFFIC_ESTIMATE` entry with the latest `created_at`,
        superseding earlier estimates rather than summing them. A
        late-arriving measured entry therefore retroactively replaces the
        estimates that preceded it for its period. The delivered total is the
        sum of the per-period values, ..."

        Design: Difficulty/dual_variant_calc/impressions_estimated_vs_measured_diverge
        """
        bundle = setup_live_flight()
        fl = bundle["flight"]["id"]
        append_impression_entry(fl, "2026-08-10", "2026-08-16",
                                "TRAFFIC_ESTIMATE", 2_400_000)
        append_impression_entry(fl, "2026-08-10", "2026-08-16",
                                "AUDIENCE_MEASURED", 1_900_000)
        append_impression_entry(fl, "2026-08-17", "2026-08-23",
                                "TRAFFIC_ESTIMATE", 2_100_000)

        flight = validate_success(api_client.get_flight(fl, SP), 200)
        assert flight["delivered_impressions"] == 4_000_000, (
            f"period 08-10..08-16 must use the 1900000 measured entry (not "
            f"the 2400000 estimate, nor a 4300000 sum) and period "
            f"08-17..08-23 the 2100000 estimate: expected 4000000, "
            f"got {flight['delivered_impressions']}"
        )

    def test_estimated_forward_looking_unchanged_by_entries(self):
        """PRD section 3.8: "The `estimated_impressions` figure is computed at
        creation and recomputed whenever the face's `daily_traffic_count` or
        `illuminated` changes, but only for flights still in `HELD`, `BOOKED`,
        or `ART_CLEARED`. For each billing week of the booked window, the
        face's `daily_traffic_count` is multiplied by seven, by the
        illumination factor — 1.12 when the face is `illuminated`, otherwise
        1.0 — and, for a `DIGITAL` face, by the slot share (`loop_slots`
        divided by `loop_slots_total`); each week's product is rounded half-up
        to a whole number of impressions, and the weekly values are then
        summed."
        PRD section 3.8: "The delivered total is the sum of the per-period
        values, and `delivery_ratio` is `delivered_impressions` divided by
        `estimated_impressions`, rounded half-up to 4 decimal places — and 0
        when no entries exist at all."

        Design: Difficulty/dual_variant_calc/impressions_estimated_vs_measured_diverge
        """
        bundle = setup_live_flight()
        fl = bundle["flight"]["id"]
        append_impression_entry(fl, "2026-08-10", "2026-08-16",
                                "TRAFFIC_ESTIMATE", 2_400_000)
        append_impression_entry(fl, "2026-08-10", "2026-08-16",
                                "AUDIENCE_MEASURED", 1_900_000)
        append_impression_entry(fl, "2026-08-17", "2026-08-23",
                                "TRAFFIC_ESTIMATE", 2_100_000)

        flight = validate_success(api_client.get_flight(fl, SP), 200)
        assert flight["estimated_impressions"] == 9_408_000, (
            f"forward-looking model is untouched by entries: "
            f"round_half_up(300000 x 7 x 1.12) = 2352000 per week x 4 weeks; "
            f"got {flight['estimated_impressions']}"
        )
        assert flight["delivery_ratio"] == 0.4252, (
            f"4000000 / 9408000 rounded half-up to 4 decimals: expected "
            f"0.4252, got {flight['delivery_ratio']}"
        )


class TestEstimatedImpressionsRecompute:

    def test_estimated_impressions_recomputed_on_traffic_update(self):
        """PRD section 3.1: "Updating a face's `daily_traffic_count` or
        `illuminated` flag increments the face's `version` and recomputes
        `estimated_impressions` for every flight on that face still in `HELD`,
        `BOOKED`, or `ART_CLEARED` (the formula lives in §3.8)."
        PRD section 3.5: "Pricing is pinned at creation and never moves again."

        Design: Corner/cross_cutting_layers/estimated_impressions_recomputed_on_traffic_update
        """
        bundle = setup_held_flight()
        flight = bundle["flight"]
        assert flight["estimated_impressions"] == 9_408_000

        resp = api_client.update_face(bundle["face"]["id"],
                                      {"daily_traffic_count": 100_000}, IM)
        get_success_data(resp)

        after = validate_success(api_client.get_flight(flight["id"], SP), 200)
        assert after["estimated_impressions"] == 3_136_000, (
            f"recompute at 100000 traffic: round_half_up(100000 x 7 x 1.12) "
            f"= 784000 per week x 4; got {after['estimated_impressions']}"
        )
        assert after["pinned_weekly_cents"] == 287_500, (
            f"price is pinned at creation and never re-rated: expected "
            f"287500, got {after['pinned_weekly_cents']}"
        )
