"""Owner reimbursement: the same formula read twice, the six-step net-payable
waterfall, and the calendar month that decides which batch a booking belongs to."""

from test_helpers import (
    ApiErrorId,
    assert_batch,
    assert_hotel,
    assert_member,
    assert_redemption,
    assert_redemption_unbatched,
    assert_stay,
    fixtures as fx,
    make_admin_headers,
    validate_error,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _cape_run_award_stayed_at_soft_occupancy(api):
    """A resort reading 0.82 occupancy and a 30,000-cent daily rate, with one
    two-night award already completed and therefore accrued."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-CPR",
        rate_category="TRANSIENT",
        name="Cape Run Resort",
        brand_code="CPR",
        market_tier="RESORT",
        program_fee_pct=0.05,
        rooms_count=120,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=1_500,
        min_tier_required="BASE",
        award_allotment_per_night=5,
    )
    funded = fx.member_funded_by_purchase(api, 100_000, channel="DIRECT_PURCHASE")
    member_id = funded["member"]["id"]

    booking = fx.book_award(
        api, member_id, hotel_id, "2026-09-10", "2026-09-12", headers=funded["member_headers"]
    )
    fx.confirm_award(api, booking["id"], headers=funded["member_headers"])
    fx.set_clock_to_day(api, "2026-09-20")
    booking = fx.complete_award_stay(api, booking["id"])

    bundle["member"] = funded["member"]
    bundle["member_headers"] = funded["member_headers"]
    bundle["booking"] = booking
    return bundle


def _grandmoor_delinquent_with_a_completed_award(api):
    """A compression-market property carrying a 700,000-cent fee ledger from one
    enormous group stay, with a completed five-night award waiting to be batched."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="GRP1",
        rate_category="GROUP",
        name="Grandmoor Convention Centre",
        brand_code="GMC",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=640,
        trailing_12m_occupancy_pct=0.96,
        trailing_12m_adr_cents=241_000,
    )
    hotel_id = bundle["hotel"]["id"]
    group_guest = fx.enroll_member(api)
    group_stay = fx.posted_stay(
        api,
        hotel_id,
        group_guest["id"],
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-06-15",
        14_000_000,
    )
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=5,
    )
    funded = fx.member_funded_by_purchase(api, 200_000, channel="DIRECT_PURCHASE")
    booking = fx.book_award(
        api,
        funded["member"]["id"],
        hotel_id,
        "2026-09-10",
        "2026-09-15",
        headers=funded["member_headers"],
    )
    fx.confirm_award(api, booking["id"], headers=funded["member_headers"])
    fx.set_clock_to_day(api, "2026-09-20")
    booking = fx.complete_award_stay(api, booking["id"])

    bundle["group_guest"] = group_guest
    bundle["group_stay"] = group_stay
    bundle["member"] = funded["member"]
    bundle["booking"] = booking
    return bundle


def _quillside_award_checking_out_on_the_first_of_october(api):
    """An award arriving 29 September and departing 1 October, completed, at a
    property whose occupancy sits exactly on the compression threshold."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-QLS",
        rate_category="TRANSIENT",
        name="Quillside Lodge",
        brand_code="QLS",
        market_tier="SELECT",
        program_fee_pct=0.03,
        rooms_count=88,
        trailing_12m_occupancy_pct=0.95,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=5,
    )
    funded = fx.member_funded_by_purchase(api, 100_000, channel="DIRECT_PURCHASE")
    booking = fx.book_award(
        api,
        funded["member"]["id"],
        hotel_id,
        "2026-09-29",
        "2026-10-01",
        headers=funded["member_headers"],
    )
    fx.confirm_award(api, booking["id"], headers=funded["member_headers"])
    fx.set_clock_to_day(api, "2026-10-02")
    booking = fx.complete_award_stay(api, booking["id"])

    bundle["member"] = funded["member"]
    bundle["booking"] = booking
    return bundle


# ----------------------------------------------------------------------
# The two readings of one formula.
# ----------------------------------------------------------------------
class TestAccrualEstimateVersusSettlementActual:
    def test_the_accrual_reading_uses_the_trailing_figures_as_they_read_at_completion(
        self, api
    ):
        """Occupancy of 0.82 lands in the strong-demand band, so each night accrues
        seventy-five percent of a 30,000-cent daily rate.

        PRD: "The **accrual** reading runs when `fulfillment_status` becomes
        `STAYED`, takes its occupancy from the property's
        `trailing_12m_occupancy_pct` and its rate from `trailing_12m_adr_cents`
        exactly as they read at that moment, and writes the result to
        `estimated_reimbursement_cents`."

        Design: Difficulty/dual_variant_calc/owner_reimbursement_accrual_estimate_vs_settlement_actual
        """
        bundle = _cape_run_award_stayed_at_soft_occupancy(api)

        assert_redemption(
            bundle["booking"],
            fulfillment_status="STAYED",
            reimbursement_status="ACCRUED",
            estimated_cents=45_000,
            settled_cents=0,
            nights=2,
            points_charged=80_000,
            cash_copay_cents=3_000,
        )

    def test_the_settlement_reading_reprices_the_same_booking_on_the_release_snapshot(
        self, api
    ):
        """A performance refresh between completion and release moves the property
        into compression, so the settlement figure is the full daily rate per night
        while the estimate stands untouched.

        PRD: "The same booking can legitimately carry two different figures: a
        two-night award at an average daily rate of 30,000 cents accrues 45,000 cents
        while occupancy reads 0.82, and settles at 60,000 cents once occupancy has
        been refreshed to 0.96."

        Design: Difficulty/dual_variant_calc/owner_reimbursement_accrual_estimate_vs_settlement_actual
        """
        bundle = _cape_run_award_stayed_at_soft_occupancy(api)
        fx.refresh_performance(api, bundle["hotel"]["id"], 0.96, 30_000)

        fx.released_batch(api, bundle["hotel"]["id"], "2026-09", releaser_id="op-release-01")

        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            fulfillment_status="STAYED",
            reimbursement_status="BATCHED",
            estimated_cents=45_000,
            settled_cents=60_000,
        )

    def test_the_batch_preserves_the_inputs_that_justify_the_difference(self, api):
        """The release snapshot is kept on the batch, which is what makes the gap
        between the estimate and the settlement auditable.

        PRD: "On a non-empty selection the batch snapshots `occupancy_pct_at_release`
        and `adr_cents_at_release` from the property, sets `item_count` to the number
        of items selected, and advances each selected booking's
        `reimbursement_status` `ACCRUED → BATCHED`, setting its `batch_id` to this
        batch and computing its `settled_reimbursement_cents` under the settlement
        reading."

        Design: Difficulty/dual_variant_calc/owner_reimbursement_accrual_estimate_vs_settlement_actual
        """
        bundle = _cape_run_award_stayed_at_soft_occupancy(api)
        fx.refresh_performance(api, bundle["hotel"]["id"], 0.96, 30_000)

        batch = fx.released_batch(
            api, bundle["hotel"]["id"], "2026-09", releaser_id="op-release-01"
        )

        assert_batch(
            batch,
            status="RELEASED",
            item_count=1,
            occupancy_at_release=0.96,
            adr_at_release=30_000,
            released_by="op-release-01",
        )
        assert (
            fx.read_redemption(api, bundle["booking"]["id"])["batch_id"] == batch["id"]
        ), "the selected booking names the batch that priced it"

    def test_a_fee_free_property_takes_the_whole_gross_as_net_payable(self, api):
        """With nothing owed in fees the offset base is zero, the two-percent band
        applies to zero, and the property is paid the gross.

        PRD: "Step one: `gross_reimbursement_cents` is the sum of
        `settled_reimbursement_cents` across the selected items."

        Design: Difficulty/dual_variant_calc/owner_reimbursement_accrual_estimate_vs_settlement_actual
        """
        bundle = _cape_run_award_stayed_at_soft_occupancy(api)
        fx.refresh_performance(api, bundle["hotel"]["id"], 0.96, 30_000)
        assert_hotel(fx.read_hotel(api, bundle["hotel"]["id"]), fee_ledger_cents=0)

        batch = fx.released_batch(
            api, bundle["hotel"]["id"], "2026-09", releaser_id="op-release-01"
        )

        assert_batch(
            batch,
            gross_cents=60_000,
            fee_offset_base_cents=0,
            surcharge_cents=0,
            total_fee_offset_cents=0,
            net_payable_cents=60_000,
        )


# ----------------------------------------------------------------------
# The surcharge tier is keyed on the working figure.
# ----------------------------------------------------------------------
class TestSurchargeTierIsKeyedOnTheWorkingFigure:
    def test_the_group_stay_earns_points_and_a_fee_without_earning_a_night(self, api):
        """Group business is fee-assessed and rewarded but never accrues elite
        nights, which is how the fee ledger reaches 700,000 cents on one stay.

        PRD: "The flag `counts_toward_elite` is true for only `TRANSIENT` and
        `CORPORATE_NEGOTIATED`: group business earns points and is fee-assessed, but
        never accrues elite nights, and that asymmetry is the whole reason
        `counts_toward_elite` exists as a flag separate from `is_qualifying`."

        Design: Difficulty/combinatorial_formula/batch_surcharge_tier_keyed_on_net_before_surcharge_not_on_final_net
        """
        bundle = _grandmoor_delinquent_with_a_completed_award(api)

        assert_stay(
            fx.read_stay(api, bundle["group_stay"]["id"]),
            status="POSTED_QUALIFYING",
            base_points=840_000,
            fee_cents=700_000,
            nights=14,
        )
        assert_member(
            fx.read_member(api, bundle["group_guest"]["id"]),
            elite_tier="BASE",
            qualifying_nights=0,
            qualifying_revenue_cents=14_000_000,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="FEE_DELINQUENT",
            fee_ledger_cents=700_000,
        )

    def test_the_fee_offset_base_is_the_ledger_balance_read_at_release(self, api):
        """The offset base is the arrears themselves, and the compression band prices
        all five award nights at the full daily rate.

        PRD: "Step two: `fee_offset_base_cents` is the property's
        `fee_ledger_balance_cents` as read at release — the programme nets what the
        property owes it in fees against what it owes the property in reimbursement."

        Design: Difficulty/combinatorial_formula/batch_surcharge_tier_keyed_on_net_before_surcharge_not_on_final_net
        """
        bundle = _grandmoor_delinquent_with_a_completed_award(api)

        batch = fx.released_batch(
            api, bundle["hotel"]["id"], "2026-09", releaser_id="op-release-02"
        )

        assert_batch(
            batch,
            status="RELEASED",
            item_count=1,
            gross_cents=1_205_000,
            fee_offset_base_cents=700_000,
        )
        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            reimbursement_status="BATCHED",
            settled_cents=1_205_000,
            points_charged=160_000,
            nights=5,
        )

    def test_the_working_figure_selects_the_one_percent_band(self, api):
        """A gross of 1,205,000 less an offset base of 700,000 leaves 505,000, which
        is at or above the high band and therefore surcharges one percent.

        PRD: "Step four: the delinquency surcharge percentage is selected from that
        step-three figure — five percent when it is negative, two percent when it is
        zero or more but below 500,000 cents, and one percent when it is 500,000
        cents or more — and `delinquency_surcharge_cents` is that percentage of
        `fee_offset_base_cents`, rounded half up once."

        Design: Difficulty/combinatorial_formula/batch_surcharge_tier_keyed_on_net_before_surcharge_not_on_final_net
        """
        bundle = _grandmoor_delinquent_with_a_completed_award(api)

        batch = fx.released_batch(
            api, bundle["hotel"]["id"], "2026-09", releaser_id="op-release-02"
        )

        assert_batch(batch, surcharge_cents=7_000, total_fee_offset_cents=707_000)

    def test_keying_the_band_on_the_final_net_would_have_paid_a_different_figure(
        self, api
    ):
        """The one-pass pin is observable: the net is 498,000, not the 491,000 that
        re-reading the band off the final net would produce.

        PRD: "With a gross of 1,205,000 cents and a fee offset base of 700,000 cents,
        step three yields 505,000, which selects the one-percent tier, giving a
        surcharge of 7,000 and a `net_payable_cents` of 498,000."

        Design: Difficulty/combinatorial_formula/batch_surcharge_tier_keyed_on_net_before_surcharge_not_on_final_net
        """
        bundle = _grandmoor_delinquent_with_a_completed_award(api)

        batch = fx.released_batch(
            api, bundle["hotel"]["id"], "2026-09", releaser_id="op-release-02"
        )

        assert batch["net_payable_cents"] == 498_000, (
            "expected 498000 from a one-percent surcharge on the arrears, got "
            f"{batch['net_payable_cents']}"
        )
        assert_batch(batch, released_by="op-release-02")


# ----------------------------------------------------------------------
# The calendar month owns the checkout date.
# ----------------------------------------------------------------------
class TestCheckoutOnTheFirstOfTheNextMonth:
    def test_occupancy_exactly_on_the_compression_threshold_pays_the_full_rate(
        self, api
    ):
        """The band comparison is inclusive, so 0.95 is compression and both nights
        accrue the undiscounted daily rate.

        PRD: "When occupancy is at or above 0.95 — compression, the property could
        certainly have sold the room — the rate per night is the full average daily
        rate, undiscounted."

        Design: Difficulty/boundary_precision_check/checkout_on_the_first_of_the_next_month_leaves_the_september_batch_empty
        """
        bundle = _quillside_award_checking_out_on_the_first_of_october(api)

        assert_redemption(
            bundle["booking"],
            fulfillment_status="STAYED",
            reimbursement_status="ACCRUED",
            estimated_cents=60_000,
            nights=2,
        )

    def test_the_september_batch_finds_nothing_and_stays_open(self, api):
        """A departure on 1 October belongs to October, so the September selection is
        empty and the batch is left where it was opened.

        PRD: "An empty selection is refused with `ERR_BATCH_NO_ELIGIBLE_ITEMS` and
        the batch stays `OPEN`."

        Design: Difficulty/boundary_precision_check/checkout_on_the_first_of_the_next_month_leaves_the_september_batch_empty
        """
        bundle = _quillside_award_checking_out_on_the_first_of_october(api)
        september = fx.open_batch(api, bundle["hotel"]["id"], "2026-09")

        response = api.release_batch(september["id"], make_admin_headers("op-release-06"))

        validate_error(response, ApiErrorId.ERR_BATCH_NO_ELIGIBLE_ITEMS.value)
        assert_batch(
            fx.read_batch(api, september["id"]),
            status="OPEN",
            item_count=0,
            gross_cents=0,
            net_payable_cents=0,
        )
        assert_redemption_unbatched(fx.read_redemption(api, bundle["booking"]["id"]))

    def test_the_october_batch_is_the_one_that_owns_the_booking(self, api):
        """The following period picks the same booking up untouched and prices it.

        PRD: "A checkout on the first day of the following month belongs to the
        following period, not this one."

        Design: Difficulty/boundary_precision_check/checkout_on_the_first_of_the_next_month_leaves_the_september_batch_empty
        """
        bundle = _quillside_award_checking_out_on_the_first_of_october(api)
        september = fx.open_batch(api, bundle["hotel"]["id"], "2026-09")
        api.release_batch(september["id"], make_admin_headers("op-release-06"))

        october = fx.released_batch(
            api, bundle["hotel"]["id"], "2026-10", releaser_id="op-release-06"
        )

        assert_batch(
            october,
            status="RELEASED",
            item_count=1,
            gross_cents=60_000,
            surcharge_cents=0,
            net_payable_cents=60_000,
        )
        booking = fx.read_redemption(api, bundle["booking"]["id"])
        assert_redemption(
            booking, reimbursement_status="BATCHED", settled_cents=60_000
        )
        assert booking["batch_id"] == october["id"], (
            "the October batch is the one that owns a 1 October departure"
        )
        assert_member(fx.read_member(api, bundle["member"]["id"]), point_balance=20_000)

    def test_the_refused_release_left_the_booking_free_to_be_batched_again(self, api):
        """Nothing was consumed by the empty selection, so the member's points and the
        booking's own figures are exactly where completion left them.

        PRD: "Bookings in `NOT_DUE`, `BATCHED`, `PAID` or `VOIDED` are all excluded —
        which is what makes a no-show, permanently `NOT_DUE`, invisible to every
        batch forever."

        Design: Difficulty/boundary_precision_check/checkout_on_the_first_of_the_next_month_leaves_the_september_batch_empty
        """
        bundle = _quillside_award_checking_out_on_the_first_of_october(api)
        september = fx.open_batch(api, bundle["hotel"]["id"], "2026-09")

        api.release_batch(september["id"], make_admin_headers("op-release-06"))

        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            reimbursement_status="ACCRUED",
            estimated_cents=60_000,
            settled_cents=0,
        )
        assert_member(fx.read_member(api, bundle["member"]["id"]), point_balance=20_000)
