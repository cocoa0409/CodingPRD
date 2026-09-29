"""Which of two overlapping price windows governs an arrival, where the two volume
discount boundaries actually sit, and how the fund's liability and solvency figures
round."""

from test_helpers import (
    assert_fund,
    assert_fund_posture_matches_ratio,
    assert_member,
    assert_purchase,
    assert_redemption,
    factories as fac,
    fixtures as fx,
    make_admin_headers,
    make_auditor_headers,
    make_care_agent_headers,
    make_member_headers,
    validate_success,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _seasonal_spire_with_a_peak_row_inside_a_year_long_standard_row(api):
    """An urban property whose year-long standard window is overlapped by a narrow
    Christmas peak window, and one funded guest arriving inside the narrow one."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR",
        rate_category="TRANSIENT",
        name="Seasonal Spire",
        brand_code="SSP",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=130,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    standard = fx.publish_pricing(
        api,
        hotel_id,
        season="STANDARD",
        window_start_date="2026-01-01",
        window_end_date="2026-12-31",
        points_per_night=20_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=2,
    )
    peak = fx.publish_pricing(
        api,
        hotel_id,
        season="PEAK",
        window_start_date="2026-12-20",
        window_end_date="2026-12-27",
        points_per_night=50_000,
        cash_copay_cents=2_500,
        min_tier_required="BASE",
        award_allotment_per_night=1,
    )
    funded = fx.member_funded_by_purchase(
        api,
        200_000,
        channel="DIRECT_PURCHASE",
        email="ss1@example.com",
        full_name="Rafal Kowal",
        enrollment_date="2026-01-06",
    )
    booking = fx.book_award(
        api,
        funded["member"]["id"],
        hotel_id,
        "2026-12-22",
        "2026-12-24",
        headers=funded["member_headers"],
    )

    bundle["standard_row"] = standard
    bundle["peak_row"] = peak
    bundle["member"] = funded["member"]
    bundle["purchase"] = funded["purchase"]
    bundle["member_headers"] = funded["member_headers"]
    bundle["booking"] = booking
    return bundle


def _five_purchases_straddling_both_volume_boundaries(api):
    """Two guests with no history, buying quantities that sit on either side of both
    discount boundaries, plus one co-brand sale."""
    first = fx.enroll_member(
        api,
        email="vt1@example.com",
        full_name="Nadia Farouk",
        enrollment_date="2026-01-09",
    )
    second = fx.enroll_member(
        api,
        email="vt2@example.com",
        full_name="Emre Kaplan",
        enrollment_date="2026-01-10",
    )
    care = make_care_agent_headers("care-vt-01")

    def _buy(member_id, quantity, headers, channel="DIRECT_PURCHASE"):
        return validate_success(
            api.create_point_purchase(
                fac.create_point_purchase_payload(
                    member_id, points_quantity=quantity, channel=channel
                ),
                headers,
            ),
            201,
        )

    second_headers = make_member_headers(second["id"])
    below_mid = _buy(second["id"], 24_000, second_headers)
    at_mid = _buy(second["id"], 25_000, second_headers)
    below_high = _buy(first["id"], 99_000, care)
    at_high = _buy(first["id"], 100_000, care)
    co_brand = _buy(
        second["id"], 20_000, make_admin_headers(), channel="CO_BRAND_CARD"
    )

    return {
        "first": first,
        "second": second,
        "below_mid": below_mid,
        "at_mid": at_mid,
        "below_high": below_high,
        "at_high": at_high,
        "co_brand": co_brand,
    }


def _one_member_and_an_untouched_fund(api):
    """A single enrolled guest whose ledger is empty, so the fund is still exactly as
    the server started it."""
    member = fx.enroll_member(
        api,
        email="pl1@example.com",
        full_name="Greta Salo",
        enrollment_date="2026-01-14",
    )
    return {"member": member}


def _fund_carrying_twenty_thousand_settled_points(api):
    """The same guest after one settled twenty-thousand-point sale, which is both the
    programme's only cash and its only outstanding liability."""
    bundle = _one_member_and_an_untouched_fund(api)
    bundle["purchase"] = fx.settled_purchase(
        api, bundle["member"]["id"], 20_000, channel="DIRECT_PURCHASE"
    )
    return bundle


# ----------------------------------------------------------------------
# Two windows cover the arrival; season rank alone decides.
# ----------------------------------------------------------------------
class TestPeakWindowOutranksAStandardWindowCoveringTheSameArrival:
    def test_the_narrow_peak_row_wins_over_the_wide_standard_row(self, api):
        """The standard window is 365 days long and was published first, and neither of
        those facts helps it once a peak window covers the arrival.

        PRD: "Candidates are ranked by `season`, with `PEAK` ranking above `STANDARD`,
        and the highest-ranked candidate wins — so where a peak window and a standard
        window both cover the arrival date, the peak price governs."

        Design: Corner/calculations/peak_window_outranks_a_standard_window_covering_the_same_arrival
        """
        bundle = _seasonal_spire_with_a_peak_row_inside_a_year_long_standard_row(api)

        assert bundle["standard_row"]["window_start_date"] == "2026-01-01", (
            "the standard row opens the year"
        )
        assert bundle["standard_row"]["window_end_date"] == "2026-12-31", (
            "the standard row runs to the end of the year"
        )
        assert bundle["peak_row"]["window_start_date"] == "2026-12-20", (
            "the peak row is the narrow one around Christmas"
        )
        assert_redemption(bundle["booking"], season="PEAK", nights=2)

    def test_every_snapshotted_field_comes_from_the_row_that_won(self, api):
        """The nightly price, the allotment and the copay are all read off the peak row,
        not blended with the standard row that also covered the date.

        PRD: "The winning row is then snapshotted onto the booking: its `season` becomes
        the booking's `season`, its `points_per_night` becomes `points_per_night_applied`,
        its `award_allotment_per_night` becomes `award_allotment_applied`, and its
        `cash_copay_cents` multiplied by `nights` becomes the booking's
        `cash_copay_cents`"

        Design: Corner/calculations/peak_window_outranks_a_standard_window_covering_the_same_arrival
        """
        bundle = _seasonal_spire_with_a_peak_row_inside_a_year_long_standard_row(api)

        assert_redemption(
            bundle["booking"],
            points_per_night=50_000,
            award_allotment=1,
            cash_copay_cents=5_000,
        )

    def test_the_urban_peak_surcharge_is_added_to_the_gross(self, api):
        """Two nights at the peak price gross 100,000 points, and the urban surcharge
        rounds up to a further 25,000.

        PRD: "Fourth, the peak surcharge: when the resolved season is `PEAK`, the gross
        is multiplied by the property's market surcharge — twenty-five percent for
        `URBAN`, thirty-five percent for `RESORT`, fifteen percent for `SELECT` — and
        that product is rounded **up** to whole points, never half up; when the season is
        `STANDARD` the surcharge is zero."

        Design: Corner/calculations/peak_window_outranks_a_standard_window_covering_the_same_arrival
        """
        bundle = _seasonal_spire_with_a_peak_row_inside_a_year_long_standard_row(api)

        assert bundle["booking"]["points_charged"] == 125_000, (
            "expected 125000 from a 100000 gross plus a 25000 urban peak surcharge, got "
            f"{bundle['booking']['points_charged']}"
        )

    def test_the_balance_falls_by_the_peak_charge_and_not_the_standard_one(self, api):
        """Had the standard row governed, the debit would have been 40,000; the guest is
        instead left with 75,000 of the 200,000 bought.

        PRD: "A `REDEEM` ledger entry is written carrying the negation of
        `points_charged` with `source_redemption_id` naming the booking, the member's
        `point_balance` falls by that amount"

        Design: Corner/calculations/peak_window_outranks_a_standard_window_covering_the_same_arrival
        """
        bundle = _seasonal_spire_with_a_peak_row_inside_a_year_long_standard_row(api)

        assert_purchase(bundle["purchase"], status="SETTLED", cash_due_cents=220_000)
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="BASE",
            point_balance=75_000,
        )


# ----------------------------------------------------------------------
# Both discount boundaries are inclusive.
# ----------------------------------------------------------------------
class TestPurchaseVolumeDiscountSwitchesAtExactlyTheTierBoundaries:
    def test_one_thousand_points_short_of_the_first_boundary_takes_no_discount(
        self, api
    ):
        """Twenty-four blocks at the direct list price is the undiscounted 30,000 cents,
        because the five-percent band starts at 25,000 points and not before.

        PRD: "The volume discount is tiered on `points_quantity` alone: twelve percent at
        100,000 points or more, five percent at 25,000 points or more, and nothing below
        that."

        Design: Corner/calculations/purchase_volume_discount_switches_at_exactly_the_tier_boundaries
        """
        bundle = _five_purchases_straddling_both_volume_boundaries(api)

        assert_purchase(
            bundle["below_mid"],
            points_quantity=24_000,
            volume_discount_pct=0.0,
            cash_due_cents=30_000,
        )

    def test_exactly_on_the_first_boundary_the_single_rounding_shows(self, api):
        """Twenty-five blocks discounted five percent is 29,687.5 cents, and the one
        rounding at the end of the whole expression takes it up to 29,688.

        PRD: "The `cash_due_cents` is the quantity in thousands multiplied by that list
        price, multiplied by one minus the discount, and rounded half up **once** at the
        end of that whole expression — rounding the discount separately or rounding the
        undiscounted price first can differ by a cent."

        Design: Corner/calculations/purchase_volume_discount_switches_at_exactly_the_tier_boundaries
        """
        bundle = _five_purchases_straddling_both_volume_boundaries(api)

        assert_purchase(
            bundle["at_mid"],
            points_quantity=25_000,
            volume_discount_pct=0.05,
            cash_due_cents=29_688,
        )

    def test_one_thousand_points_short_of_the_second_boundary_stays_on_five_percent(
        self, api
    ):
        """Ninety-nine blocks is still the middle band, and its 117,562.5 cents also
        rounds up on the half.

        PRD: "The comparisons are inclusive, so exactly 100,000 points takes the
        twelve-percent tier while 99,000 takes the five-percent tier."

        Design: Corner/calculations/purchase_volume_discount_switches_at_exactly_the_tier_boundaries
        """
        bundle = _five_purchases_straddling_both_volume_boundaries(api)

        assert_purchase(
            bundle["below_high"],
            points_quantity=99_000,
            volume_discount_pct=0.05,
            cash_due_cents=117_563,
        )

    def test_exactly_on_the_second_boundary_takes_the_twelve_percent_band(self, api):
        """One hundred blocks at the list price is 125,000 cents, and the twelve-percent
        band brings it to a round 110,000.

        PRD: "The list price per thousand points is the referenced partner's
        `points_cost_per_1000_cents` for a `PARTNER_SALE`, and a flat 1,250 cents for
        both other channels."

        Design: Corner/calculations/purchase_volume_discount_switches_at_exactly_the_tier_boundaries
        """
        bundle = _five_purchases_straddling_both_volume_boundaries(api)

        assert_purchase(
            bundle["at_high"],
            points_quantity=100_000,
            volume_discount_pct=0.12,
            cash_due_cents=110_000,
        )

    def test_the_co_brand_bonus_is_not_a_discount(self, api):
        """A twenty-thousand-point co-brand sale is charged at list and hands over two
        thousand extra points on the side.

        PRD: "Finally the co-brand bonus: `bonus_points` is ten percent of
        `points_quantity`, floored to whole points, for the `CO_BRAND_CARD` channel and 0
        for both others"

        Design: Corner/calculations/purchase_volume_discount_switches_at_exactly_the_tier_boundaries
        """
        bundle = _five_purchases_straddling_both_volume_boundaries(api)

        assert_purchase(
            bundle["co_brand"],
            channel="CO_BRAND_CARD",
            points_quantity=20_000,
            volume_discount_pct=0.0,
            cash_due_cents=25_000,
            bonus_points=2_000,
        )
        assert bundle["below_mid"]["bonus_points"] == 0, (
            "a direct purchase never earns a bonus"
        )

    def test_pricing_a_purchase_moves_no_cash_at_all(self, api):
        """All five quotes are still pending, so the fund holds nothing and none of them
        names a partner.

        PRD: "The purchase is created in status `PENDING` with `refund_reason` null."

        Design: Corner/calculations/purchase_volume_discount_switches_at_exactly_the_tier_boundaries
        """
        bundle = _five_purchases_straddling_both_volume_boundaries(api)

        for key in ("below_mid", "at_mid", "below_high", "at_high", "co_brand"):
            purchase = bundle[key]
            assert_purchase(purchase, status="PENDING")
            assert purchase["refund_reason"] is None, (
                f"{key} carries a refund reason before it was ever settled"
            )
            assert purchase["partner_id"] is None, (
                f"{key} names a partner although no partner was referenced"
            )
        assert_fund(fx.read_fund(api), cash_cents=0, outstanding_points=0)


# ----------------------------------------------------------------------
# Liability to the cent, solvency to four decimals.
# ----------------------------------------------------------------------
class TestLiabilityRoundsToTheCentAndSolvencyToFourDecimals:
    def test_an_empty_ledger_is_pinned_rather_than_divided_by_zero(self, api):
        """Nothing has ever moved, so the fund reads its opening figures and the ratio is
        the sentinel rather than an arithmetic error.

        PRD: "The `solvency_ratio` is `cash_balance_cents` divided by
        `point_liability_cents`, rounded half up to four decimal places, and is pinned to
        exactly 999.0000 when the liability is zero rather than dividing by zero — so a
        programme with an empty ledger reads `HEALTHY`, not impaired."

        Design: Corner/calculations/liability_rounds_to_the_cent_and_solvency_to_four_decimals
        """
        _one_member_and_an_untouched_fund(api)

        fund = validate_success(api.get_program_fund(make_auditor_headers()))

        assert_fund(
            fund,
            cash_cents=0,
            outstanding_points=0,
            liability_cents=0,
            solvency_ratio=999.0,
            status="HEALTHY",
            breakage_rate_pct=0.2,
        )

    def test_outstanding_points_value_at_six_hundred_less_the_breakage(self, api):
        """Twenty thousand points at 600 cents a thousand is 12,000 cents gross, and the
        default one-fifth breakage assumption values them at 9,600.

        PRD: "The `point_liability_cents` is that outstanding total, valued at 600 cents
        per thousand points, multiplied by one minus `breakage_rate_pct`, rounded half up
        to whole cents."

        Design: Corner/calculations/liability_rounds_to_the_cent_and_solvency_to_four_decimals
        """
        bundle = _fund_carrying_twenty_thousand_settled_points(api)

        fund = fx.read_fund(api)

        assert_purchase(bundle["purchase"], status="SETTLED", cash_due_cents=25_000)
        assert_fund(fund, outstanding_points=20_000, liability_cents=9_600)

    def test_the_solvency_ratio_is_rounded_at_the_fourth_decimal(self, api):
        """Twenty-five thousand cents of cash against a 9,600-cent liability is
        2.60416666, which the fund records as 2.6042.

        PRD: "The posture then follows: `HEALTHY` at a ratio of 1.0000 or above, `WATCH`
        from 0.7500 up to but not including 1.0000, and `IMPAIRED` below 0.7500."

        Design: Corner/calculations/liability_rounds_to_the_cent_and_solvency_to_four_decimals
        """
        _fund_carrying_twenty_thousand_settled_points(api)

        fund = fx.read_fund(api)

        assert_fund(fund, cash_cents=25_000, solvency_ratio=2.6042, status="HEALTHY")
        assert_fund_posture_matches_ratio(fund)

    def test_an_odd_lot_grant_and_a_restated_assumption_land_on_a_half_cent(self, api):
        """Fifty goodwill points take the outstanding total to 20,050, which at
        thirty-five percent breakage values at exactly 7,819.5 cents and rounds up.

        PRD: "An administrator may additionally restate the assumption by supplying a new
        `breakage_rate_pct` between 0.0 and 0.35 inclusive; that overwrites the field,
        immediately re-runs the valuation and posture derivation, and increments the
        `version`"

        Design: Corner/calculations/liability_rounds_to_the_cent_and_solvency_to_four_decimals
        """
        bundle = _fund_carrying_twenty_thousand_settled_points(api)
        member_id = bundle["member"]["id"]
        entry = validate_success(
            api.create_point_adjustment(
                fac.point_adjustment_payload(
                    member_id,
                    50,
                    fx.member_version(api, member_id),
                    adjustment_reason="Odd-lot goodwill top-up.",
                ),
                make_care_agent_headers("care-pl-01"),
            ),
            201,
        )

        fund = fx.set_breakage_rate(api, 0.35)

        assert entry["points"] == 50, f"the grant moved {entry['points']} points, not 50"
        assert_member(fx.read_member(api, member_id), point_balance=20_050)
        assert_fund(
            fund,
            breakage_rate_pct=0.35,
            outstanding_points=20_050,
            liability_cents=7_820,
        )

    def test_restating_the_assumption_leaves_the_revaluation_stamp_alone(self, api):
        """The new solvency figure is derived immediately, and the stamp that records an
        explicit revaluation is still unset.

        PRD: "but it does **not** touch `last_revalued_at`, which records only an
        explicit revaluation."

        Design: Corner/calculations/liability_rounds_to_the_cent_and_solvency_to_four_decimals
        """
        bundle = _fund_carrying_twenty_thousand_settled_points(api)
        member_id = bundle["member"]["id"]
        fx.grant_goodwill_points(api, member_id, 50, reason="Odd-lot goodwill top-up.")

        fund = fx.set_breakage_rate(api, 0.35)

        assert_fund(fund, solvency_ratio=3.1969, status="HEALTHY")
        assert_fund_posture_matches_ratio(fund)
        assert fund["last_revalued_at"] is None, (
            "restating the breakage assumption is not an explicit revaluation, so the "
            f"stamp should still be unset, got {fund['last_revalued_at']}"
        )
