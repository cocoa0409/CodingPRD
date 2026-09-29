"""Dual-variant settlement arithmetic and composed money formulas.

Every test builds its own world through the declared endpoints, because the
database is emptied before each one runs.
"""

import pytest

from test_helpers import (
    apply_pct_to_cents,
    assert_coop_is_lesser_leg,
    assert_market_exposure,
    assert_waterfall_buckets,
    expected_adjusted_gross,
    get_success_data,
    pct_of,
    round_half_up,
    validate_success,
    whole_percent_of,
)


# ---------------------------------------------------------------------------
# Expected figures, derived from the contract rather than copied as literals
# where the derivation is itself part of what is under test.
# ---------------------------------------------------------------------------

# The 3000-seat co-promote show, valued the FINAL way: 800 GA at 5000, 600 GA at
# the revised 6000 and 400 PIT at 9500, for 1800 paid tickets.
FINAL_GROSS_RECEIPTS = 800 * 5_000 + 600 * 6_000 + 400 * 9_500
FINAL_PAID_TICKETS = 800 + 600 + 400

# The same show valued the PROVISIONAL way: the whole sellable allocation at the
# price each tier carries today (GA 2000 less 60 comps at 6000, PIT 500 less 50
# held at 9500).
PROVISIONAL_GA_SELLABLE = 2_000 - 60
PROVISIONAL_PIT_SELLABLE = 500 - 50
PROVISIONAL_GROSS_RECEIPTS = (
    PROVISIONAL_GA_SELLABLE * 6_000 + PROVISIONAL_PIT_SELLABLE * 9_500
)
PROVISIONAL_PAID_TICKETS = PROVISIONAL_GA_SELLABLE + PROVISIONAL_PIT_SELLABLE

HARBOR_TICKET_TAX_PCT = 8.00
HARBOR_FACILITY_FEE = 350

FINAL_BUCKETS = expected_adjusted_gross(
    FINAL_GROSS_RECEIPTS, HARBOR_TICKET_TAX_PCT, FINAL_PAID_TICKETS, HARBOR_FACILITY_FEE
)
PROVISIONAL_BUCKETS = expected_adjusted_gross(
    PROVISIONAL_GROSS_RECEIPTS,
    HARBOR_TICKET_TAX_PCT,
    PROVISIONAL_PAID_TICKETS,
    HARBOR_FACILITY_FEE,
)


def _fixture_a(build):
    """The 3000-seat co-promote show, carried to PERFORMED with resolved books.

    Four budget lines: PRODUCTION 1,500,000 budgeted against 1,650,000 invoiced
    (exactly 10.00 percent, so it stays within tolerance and recognises the
    actual), MARKETING 800,000 against 900,000 with an approved cap of 900,000,
    STAFFING 600,000 against 600,000 and not artist-deductible, and HOSPITALITY
    200,000 against 260,000 with an approved cap of 250,000.
    """
    return build.big_copromote_show()


def _live_rental_show_in(build, market_id):
    """A second, still-selling RENTAL show sharing one market with fixture A."""
    artist = build.artist(
        name="Nord Trio",
        agency="Fjord Bookings",
        tier="CLUB",
        historical_sellthrough_pct=55.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market_id,
        name="Riverside Hall",
        gross_capacity=1_200,
        facility_fee_cents_per_ticket=300,
        ticket_tax_pct=10.00,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-11-05T02:00:00.000Z",
        load_in_at="2026-11-04T16:00:00.000Z",
        load_out_at="2026-11-05T08:00:00.000Z",
        announce_at="2026-10-10T15:00:00.000Z",
        venue_arrangement="RENTAL",
        rental_fee_cents=500_000,
    )
    offer = build.accepted_offer(
        show["id"],
        artist["id"],
        expected_show_version=show["version"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=2_000_000,
        deposit_cents=500_000,
        expense_cap_cents=2_000_000,
    )
    ga = build.tier(show["id"], tier_name="GA", price_cents=5_000, allocation_qty=1_000)
    line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="backline rental and local crew",
        budgeted_cents=500_000,
        is_artist_deductible=True,
    )
    build.set_clock("2026-10-10T15:00:00.000Z")
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(ga["id"], 400)
    return {
        "artist": artist,
        "venue": venue,
        "show": build.read_show(show["id"]),
        "offer": offer,
        "ga": build.read_tier(ga["id"]),
        "line": build.read_budget_line(line["id"]),
    }


# The three-line co-promote fixture: identical PRODUCTION lines whose per-line
# reimbursement does not divide evenly into whole cents.
THREE_LINE_EXPENSE = 250_005
THREE_LINE_COUNT = 3
PRODUCTION_SHARE_PCT = 33.50
PER_LINE_REIMBURSEMENT = apply_pct_to_cents(THREE_LINE_EXPENSE, PRODUCTION_SHARE_PCT)
PER_LINE_MODE_TOTAL = PER_LINE_REIMBURSEMENT * THREE_LINE_COUNT
CATEGORY_TOTAL_EXPENSE = THREE_LINE_EXPENSE * THREE_LINE_COUNT
AGGREGATE_MODE_TOTAL = apply_pct_to_cents(CATEGORY_TOTAL_EXPENSE, PRODUCTION_SHARE_PCT)


def _three_line_copromote_show(build):
    """A losing co-promote show at a zero-tax, zero-facility-fee venue.

    Three PRODUCTION lines of 250,005 cents each, every one invoiced at exactly
    its budget so no variance is outstanding, and a 33.50 percent production
    share for the building.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Great Lakes", region_code="GLK", guarantee_exposure_limit_cents=10_000_000
    )
    artist = build.artist(
        name="Delta Quartet",
        agency="Riverbend Artists",
        tier="CLUB",
        historical_sellthrough_pct=60.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name="Civic Theater",
        gross_capacity=900,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-09-20T02:00:00.000Z",
        load_in_at="2026-09-19T14:00:00.000Z",
        load_out_at="2026-09-20T08:00:00.000Z",
        announce_at="2026-08-10T15:00:00.000Z",
        venue_arrangement="CO_PROMOTE",
        copromote_venue_share_pct=10.00,
        venue_expense_pct_production=PRODUCTION_SHARE_PCT,
        venue_expense_pct_marketing=0,
        venue_expense_pct_staffing=0,
        venue_expense_pct_hospitality=0,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        expected_show_version=show["version"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ga = build.tier(show["id"], tier_name="GA", price_cents=1_000, allocation_qty=800)
    descriptions = [
        "line 1 of 3 - audio package",
        "line 2 of 3 - lighting package",
        "line 3 of 3 - stage and rigging",
    ]
    lines = [
        build.budget_line(
            show["id"],
            category="PRODUCTION",
            description=description,
            budgeted_cents=THREE_LINE_EXPENSE,
            is_artist_deductible=False,
        )
        for description in descriptions
    ]
    build.set_clock("2026-08-10T15:00:00.000Z")
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(ga["id"], 400)
    for index, line in enumerate(lines, start=1):
        build.approved_invoice(
            show["id"],
            line["id"],
            THREE_LINE_EXPENSE,
            vendor_name=f"Lakeshore Supplier {index}",
            invoice_date="2026-09-19",
            documentation_ref=f"INV-C-{index:04d}",
        )
    build.set_clock("2026-09-20T06:00:00.000Z")
    get_success_data(build.api.perform_show(show["id"], build.accountant))
    return {
        "market": build.read_market(market["id"]),
        "venue": build.read_venue(venue["id"]),
        "show": build.read_show(show["id"]),
        "ga": build.read_tier(ga["id"]),
        "lines": [build.read_budget_line(line["id"]) for line in lines],
        "settlement": build.settlement(show["id"]),
    }


# The co-op fixture: two shows whose recognised marketing expense is identical
# and whose only difference is the guarantee that becomes the artist's base.
COOP_MARKETING_EXPENSE = 200_000
COOP_SHARE_LEG = apply_pct_to_cents(COOP_MARKETING_EXPENSE, 50)
CAP_BINDING_GUARANTEE = 1_000_010
SHARE_BINDING_GUARANTEE = 5_000_000
COOP_TICKETS_SOLD = 200
COOP_TICKET_PRICE = 2_000
COOP_RENTAL_FEE = 100_000
COOP_BUCKETS = expected_adjusted_gross(
    COOP_TICKETS_SOLD * COOP_TICKET_PRICE, 0, COOP_TICKETS_SOLD, 0
)


def _coop_leg_shows(build):
    """Two RENTAL shows identical but for the guarantee that sets the base.

    Both recognise the same 200,000 cents of marketing expense, and neither
    marketing line is artist-deductible, so the only input that moves between
    them is the guarantee.
    """
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Mountain West",
        region_code="MTW",
        guarantee_exposure_limit_cents=10_000_000,
    )
    artist = build.artist(
        name="Signal Fire",
        agency="High Desert Talent",
        tier="THEATER",
        historical_sellthrough_pct=48.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name="Foothills Ballroom",
        gross_capacity=900,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )

    def one_show(event_at, load_in_at, load_out_at, guarantee_cents, reference):
        show = build.show(
            artist["id"],
            venue["id"],
            event_at=event_at,
            load_in_at=load_in_at,
            load_out_at=load_out_at,
            announce_at="2026-08-05T15:00:00.000Z",
            venue_arrangement="RENTAL",
            rental_fee_cents=COOP_RENTAL_FEE,
        )
        build.accepted_offer(
            show["id"],
            artist["id"],
            expected_show_version=show["version"],
            deal_structure="FLAT_GUARANTEE",
            guarantee_cents=guarantee_cents,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
        )
        tier = build.tier(
            show["id"],
            tier_name="GA",
            price_cents=COOP_TICKET_PRICE,
            allocation_qty=500,
        )
        line = build.budget_line(
            show["id"],
            category="MARKETING",
            description="co-op radio and print buy",
            budgeted_cents=COOP_MARKETING_EXPENSE,
            is_artist_deductible=False,
        )
        return {"show": show, "tier": tier, "line": line, "reference": reference}

    cap = one_show(
        "2026-09-20T02:00:00.000Z",
        "2026-09-19T14:00:00.000Z",
        "2026-09-20T08:00:00.000Z",
        CAP_BINDING_GUARANTEE,
        "E1",
    )
    share = one_show(
        "2026-10-15T02:00:00.000Z",
        "2026-10-14T14:00:00.000Z",
        "2026-10-15T08:00:00.000Z",
        SHARE_BINDING_GUARANTEE,
        "E2",
    )
    build.set_clock("2026-08-05T15:00:00.000Z")
    for leg in (cap, share):
        get_success_data(build.api.put_show_on_sale(leg["show"]["id"], build.buyer))
    for leg in (cap, share):
        build.sell(leg["tier"]["id"], COOP_TICKETS_SOLD)
    for leg, invoice_date in ((cap, "2026-09-19"), (share, "2026-10-14")):
        build.approved_invoice(
            leg["show"]["id"],
            leg["line"]["id"],
            COOP_MARKETING_EXPENSE,
            vendor_name="Summit Media",
            invoice_date=invoice_date,
            documentation_ref=f"INV-{leg['reference']}-0001",
        )
    for leg, perform_at in (
        (cap, "2026-09-20T06:00:00.000Z"),
        (share, "2026-10-15T06:00:00.000Z"),
    ):
        build.set_clock(perform_at)
        get_success_data(build.api.perform_show(leg["show"]["id"], build.accountant))
        leg["settlement"] = build.settlement(leg["show"]["id"])
        leg["line"] = build.read_budget_line(leg["line"]["id"])
    return {"market": market, "artist": artist, "venue": venue, "cap": cap, "share": share}


class TestProvisionalVersusFinalSettlement:
    """The same stored show, valued two ways."""

    def test_provisional_projection_values_the_whole_sellable_allocation_at_current_prices(
        self, api, build
    ):
        """PRD section 3.7: "The **provisional** variant values the entire sellable
        allocation at the **current** price: for each tier, take its `allocation_qty`
        less its `comp_qty` less its `held_qty`, multiply by that tier's current
        `price_cents`, and sum across tiers to get a projected gross"

        Design: Difficulty/dual_variant_calc/settlement_projection_provisional_versus_final_diverge_on_identical_show
        """
        ctx = _fixture_a(build)

        projection = validate_success(
            api.get_settlement_projection(ctx["show"]["id"], build.accountant)
        )

        assert projection["gross_receipts_cents"] == PROVISIONAL_GROSS_RECEIPTS == 15_915_000
        assert_waterfall_buckets(projection, PROVISIONAL_BUCKETS)
        assert projection["adjusted_gross_cents"] == 13_439_255
        assert ctx["show"]["projected_adjusted_gross_cents"] == 13_439_255

    def test_provisional_projection_is_a_transient_object_that_persists_nothing(
        self, api, build
    ):
        """PRD section 3.7: "Its result is a settlement-shaped transient object in
        which `id`, `created_at`, `updated_at` and `version` are all null, `status`
        is reported as `DRAFT`" — and "it neither creates, reads nor mutates any
        settlement row"

        Design: Difficulty/dual_variant_calc/settlement_projection_provisional_versus_final_diverge_on_identical_show
        """
        ctx = _fixture_a(build)
        book = build.settlement(ctx["show"]["id"])

        projection = validate_success(
            api.get_settlement_projection(ctx["show"]["id"], build.accountant)
        )

        assert projection["id"] is None
        assert projection["created_at"] is None
        assert projection["updated_at"] is None
        assert projection["version"] is None
        assert projection["status"] == "DRAFT"
        assert projection["show_id"] == ctx["show"]["id"]

        untouched = build.read_settlement(book["id"])
        assert untouched["status"] == "DRAFT"
        assert untouched["adjusted_gross_cents"] == 0
        assert untouched["version"] == book["version"]

    def test_provisional_projection_deducts_budgeted_expense_and_lands_on_its_share_leg(
        self, api, build
    ):
        """PRD section 3.7: "On the expense side the provisional variant uses
        **budgeted** amounts rather than recognised ones: the deductible base is the
        sum of `budgeted_cents` across the artist-deductible lines (still subject to
        the offer's `expense_cap_cents`), the marketing co-op share leg is computed
        against budgeted marketing expense"

        Design: Difficulty/dual_variant_calc/settlement_projection_provisional_versus_final_diverge_on_identical_show
        """
        ctx = _fixture_a(build)

        projection = validate_success(
            api.get_settlement_projection(ctx["show"]["id"], build.accountant)
        )

        # Budgeted, not recognised: 1,500,000 + 800,000 + 600,000 + 200,000.
        assert projection["total_settlement_expense_cents"] == 3_100_000
        # Deductible budgets only, under the 4,000,000 cap.
        assert projection["allowed_expense_cents"] == 2_500_000
        assert projection["breakeven_cents"] == 2_500_000 + 5_000_000 == 7_500_000
        overage = 13_439_255 - 7_500_000
        assert projection["artist_base_earnings_cents"] == (
            5_000_000 + apply_pct_to_cents(overage, 85.00)
        ) == 10_048_367
        assert_coop_is_lesser_leg(
            projection["artist_coop_contribution_cents"], 800_000, 10_048_367
        )
        assert projection["artist_coop_contribution_cents"] == 400_000
        assert projection["artist_earnings_cents"] == 10_048_367 - 400_000 == 9_648_367

    def test_final_calculation_values_only_the_tickets_that_actually_sold(self, api, build):
        """PRD section 3.7: "The **final** variant, which is what the settlement
        calculation runs, values only the tickets that actually sold, at the price
        each sale carried, and deducts recognised expenses"

        Design: Difficulty/dual_variant_calc/settlement_projection_provisional_versus_final_diverge_on_identical_show
        """
        ctx = _fixture_a(build)
        book = build.settlement(ctx["show"]["id"])

        settled = validate_success(api.calculate_settlement(book["id"], build.accountant))

        assert settled["status"] == "CALCULATED"
        assert settled["gross_receipts_cents"] == FINAL_GROSS_RECEIPTS == 11_400_000
        assert_waterfall_buckets(settled, FINAL_BUCKETS)
        assert settled["adjusted_gross_cents"] == 9_595_800
        # Recognised, not actual: the hospitality overage is capped at 250,000.
        assert settled["total_settlement_expense_cents"] == 3_400_000
        assert settled["allowed_expense_cents"] == 2_800_000
        assert settled["breakeven_cents"] == 7_800_000

    def test_final_calculation_lands_on_its_cap_leg_not_the_provisional_share_leg(
        self, api, build
    ):
        """PRD section 3.7: "The **cap leg** is 5 percent of
        `artist_base_earnings_cents`, likewise rounded half up to whole cents.
        `artist_coop_contribution_cents` is the **lesser** of the two legs"

        Design: Difficulty/dual_variant_calc/settlement_projection_provisional_versus_final_diverge_on_identical_show
        """
        ctx = _fixture_a(build)
        book = build.settlement(ctx["show"]["id"])

        settled = validate_success(api.calculate_settlement(book["id"], build.accountant))

        overage = 9_595_800 - 7_800_000
        assert settled["artist_base_earnings_cents"] == (
            5_000_000 + apply_pct_to_cents(overage, 85.00)
        ) == 6_526_430
        assert_coop_is_lesser_leg(
            settled["artist_coop_contribution_cents"], 900_000, 6_526_430
        )
        # 5 percent of 6,526,430 is 326,321.5 and rounds half up, away from zero.
        assert settled["artist_coop_contribution_cents"] == 326_322
        assert settled["artist_earnings_cents"] == 6_526_430 - 326_322 == 6_200_108
        assert settled["payment_due_cents"] == 6_200_108 - 0 - 1_000_000 == 5_200_108

    def test_the_two_variants_diverge_and_the_binding_coop_leg_switches(self, api, build):
        """PRD section 3.7: "Because the provisional variant's co-op contribution can
        land on its share leg while the final variant's lands on its cap leg, even the
        binding constraint can switch between the two."

        Design: Difficulty/dual_variant_calc/settlement_projection_provisional_versus_final_diverge_on_identical_show
        """
        ctx = _fixture_a(build)
        book = build.settlement(ctx["show"]["id"])

        projection = validate_success(
            api.get_settlement_projection(ctx["show"]["id"], build.accountant)
        )
        settled = validate_success(api.calculate_settlement(book["id"], build.accountant))

        assert projection["adjusted_gross_cents"] - settled["adjusted_gross_cents"] == 3_843_455
        assert projection["artist_earnings_cents"] - settled["artist_earnings_cents"] == 3_448_259

        provisional_share_leg = apply_pct_to_cents(800_000, 50)
        provisional_cap_leg = apply_pct_to_cents(10_048_367, 5)
        final_share_leg = apply_pct_to_cents(900_000, 50)
        final_cap_leg = apply_pct_to_cents(6_526_430, 5)
        assert provisional_share_leg < provisional_cap_leg
        assert final_cap_leg < final_share_leg
        assert projection["artist_coop_contribution_cents"] == provisional_share_leg
        assert settled["artist_coop_contribution_cents"] == final_cap_leg
        assert (
            projection["artist_coop_contribution_cents"]
            != settled["artist_coop_contribution_cents"]
        )

        show = build.read_show(ctx["show"]["id"])
        assert show["projected_adjusted_gross_cents"] == 13_439_255
        assert show["adjusted_gross_cents"] == 9_595_800


SETTLED_PROMOTER_NET = 1_398_838
SETTLED_PROJECTED_PROMOTER_NET = 5_339_255
LIVE_PROJECTED_PROMOTER_NET = 1_587_500
LIVE_PAID_TICKETS = 400
LIVE_ALLOCATION = 1_000


def _market_with_one_settled_and_one_live_show(build):
    """One market carrying a fully paid show and a still-selling show."""
    ctx = _fixture_a(build)
    paid = build.paid_settlement(ctx["show"]["id"], ctx["artist"]["id"])
    live = _live_rental_show_in(build, ctx["market"]["id"])
    return {
        "market_id": ctx["market"]["id"],
        "settled_show": build.read_show(ctx["show"]["id"]),
        "settled_settlement": build.read_settlement(paid["id"]),
        "live": live,
    }


class TestPerformanceIndexValuations:
    """One market, two valuations of the same stored shows."""

    def test_trailing_settled_valuation_counts_only_the_settled_show(self, api, build):
        """PRD section 3.3: "Under the **`TRAILING_SETTLED`** valuation, the numerator
        is the sum of `promoter_net_cents` over the settlements of the market's shows
        whose `show_status` is `SETTLED`, and the denominator is the sum of
        `projected_promoter_net_cents` over those same settled shows."

        Design: Difficulty/dual_variant_calc/market_performance_index_trailing_settled_versus_mark_to_market
        """
        ctx = _market_with_one_settled_and_one_live_show(build)

        assert ctx["settled_show"]["show_status"] == "SETTLED"
        assert ctx["settled_settlement"]["status"] == "PAID"
        assert ctx["settled_settlement"]["promoter_net_cents"] == SETTLED_PROMOTER_NET
        assert (
            ctx["settled_show"]["projected_promoter_net_cents"]
            == SETTLED_PROJECTED_PROMOTER_NET
        )

        market = validate_success(
            api.get_portfolio_risk(
                ctx["market_id"], build.risk, valuation="TRAILING_SETTLED"
            )
        )

        assert market["performance_index"] == whole_percent_of(
            SETTLED_PROMOTER_NET, SETTLED_PROJECTED_PROMOTER_NET
        ) == 26

    def test_mark_to_market_valuation_additionally_marks_in_the_live_show(self, api, build):
        """PRD section 3.3: "Each live show's contribution to the numerator is its
        `projected_promoter_net_cents` multiplied by its `paid_tickets_sold`, divided
        by the total `allocation_qty` across that show's tiers, rounded half up to
        whole cents"

        Design: Difficulty/dual_variant_calc/market_performance_index_trailing_settled_versus_mark_to_market
        """
        ctx = _market_with_one_settled_and_one_live_show(build)

        live_show = ctx["live"]["show"]
        assert live_show["show_status"] == "ON_SALE"
        assert live_show["paid_tickets_sold"] == LIVE_PAID_TICKETS
        assert live_show["projected_promoter_net_cents"] == LIVE_PROJECTED_PROMOTER_NET
        assert live_show["adjusted_gross_cents"] == 1_635_000

        mark = round_half_up(
            LIVE_PROJECTED_PROMOTER_NET * LIVE_PAID_TICKETS / LIVE_ALLOCATION
        )
        assert mark == 635_000

        market = validate_success(
            api.get_portfolio_risk(
                ctx["market_id"], build.risk, valuation="MARK_TO_MARKET"
            )
        )

        assert market["performance_index"] == whole_percent_of(
            SETTLED_PROMOTER_NET + mark,
            SETTLED_PROJECTED_PROMOTER_NET + LIVE_PROJECTED_PROMOTER_NET,
        ) == 29

    def test_the_two_valuations_disagree_on_identical_stored_data(self, api, build):
        """PRD section 3.3: "a `MARK_TO_MARKET` valuation is returned in the response
        body only and never overwrites the stored `Market.performance_index`, which is
        always the `TRAILING_SETTLED` figure."

        Design: Difficulty/dual_variant_calc/market_performance_index_trailing_settled_versus_mark_to_market
        """
        ctx = _market_with_one_settled_and_one_live_show(build)

        trailing = validate_success(
            api.get_portfolio_risk(
                ctx["market_id"], build.risk, valuation="TRAILING_SETTLED"
            )
        )
        mark_to_market = validate_success(
            api.get_portfolio_risk(
                ctx["market_id"], build.risk, valuation="MARK_TO_MARKET"
            )
        )

        assert trailing["performance_index"] == 26
        assert mark_to_market["performance_index"] == 29
        assert trailing["performance_index"] != mark_to_market["performance_index"]

        stored = build.read_market(ctx["market_id"])
        assert stored["performance_index"] == 26
        assert stored["settled_show_count"] == 1
        assert_market_exposure(stored, 2_000_000, 20.00, "OPEN")
        assert stored["exposure_utilization_pct"] == pytest.approx(
            pct_of(2_000_000, 10_000_000), abs=0.01
        )


class TestCoPromoteVenueReimbursementRounding:
    """Where the half-up rounding sits inside the reimbursement aggregation."""

    def test_reimbursement_rounds_once_per_line_and_the_rounded_amounts_are_summed(
        self, api, build
    ):
        """PRD section 3.7: "Under `CO_PROMOTE`,
        `venue_expense_reimbursement_cents` is computed **per line and rounded per
        line, then summed**"

        Design: Difficulty/combinatorial_formula/venue_reimbursement_rounds_per_line_not_on_the_category_total
        """
        ctx = _three_line_copromote_show(build)

        for line in ctx["lines"]:
            assert line["settlement_expense_cents"] == THREE_LINE_EXPENSE
            assert line["variance_pct"] == pytest.approx(0.00, abs=0.01)
            assert line["variance_status"] == "WITHIN_TOLERANCE"

        settled = validate_success(
            api.calculate_settlement(ctx["settlement"]["id"], build.accountant)
        )

        assert settled["total_settlement_expense_cents"] == CATEGORY_TOTAL_EXPENSE == 750_015
        assert PER_LINE_REIMBURSEMENT == 83_752
        assert settled["venue_expense_reimbursement_cents"] == PER_LINE_MODE_TOTAL == 251_256

    def test_rounding_the_category_total_once_is_observably_one_cent_lower(self, api, build):
        """PRD section 3.7: "This is normative: rounding a category total once, or
        rounding a blended percentage against the aggregate expense, differs by cents
        from the per-line mode and the difference is observable."

        Design: Difficulty/combinatorial_formula/venue_reimbursement_rounds_per_line_not_on_the_category_total
        """
        ctx = _three_line_copromote_show(build)

        settled = validate_success(
            api.calculate_settlement(ctx["settlement"]["id"], build.accountant)
        )

        assert AGGREGATE_MODE_TOTAL == 251_255
        assert PER_LINE_MODE_TOTAL - AGGREGATE_MODE_TOTAL == 1
        assert settled["venue_expense_reimbursement_cents"] != AGGREGATE_MODE_TOTAL
        assert settled["venue_expense_reimbursement_cents"] == PER_LINE_MODE_TOTAL

    def test_promoter_borne_expense_is_the_recognised_total_less_the_per_line_reimbursement(
        self, api, build
    ):
        """PRD section 3.7: "`promoter_borne_expense_cents` is
        `total_settlement_expense_cents` less `venue_expense_reimbursement_cents`. Then
        form net-before-venue-share as `adjusted_gross_cents` less
        `artist_earnings_cents` less `promoter_borne_expense_cents`"

        Design: Difficulty/combinatorial_formula/venue_reimbursement_rounds_per_line_not_on_the_category_total
        """
        ctx = _three_line_copromote_show(build)

        settled = validate_success(
            api.calculate_settlement(ctx["settlement"]["id"], build.accountant)
        )

        assert settled["promoter_borne_expense_cents"] == (
            CATEGORY_TOTAL_EXPENSE - PER_LINE_MODE_TOTAL
        ) == 498_759

    def test_a_losing_copromote_floors_the_building_share_and_the_invariant_still_closes(
        self, api, build
    ):
        """PRD section 3.7: "On a co-promote loss the building's share is zero — the
        floor in the venue-share step guarantees it — and the whole loss stays with the
        promoter." The closing invariant is that "`adjusted_gross_cents` equals
        `artist_earnings_cents` plus `promoter_borne_expense_cents` plus
        `venue_share_cents` plus `promoter_net_cents`".

        Design: Difficulty/combinatorial_formula/venue_reimbursement_rounds_per_line_not_on_the_category_total
        """
        ctx = _three_line_copromote_show(build)

        settled = validate_success(
            api.calculate_settlement(ctx["settlement"]["id"], build.accountant)
        )

        assert settled["ticket_tax_cents"] == 0
        assert settled["facility_fee_cents"] == 0
        assert settled["credit_card_fee_cents"] == 10_000
        assert settled["adjusted_gross_cents"] == 390_000
        # No line is artist-deductible, so the flat guarantee is the whole base.
        assert settled["allowed_expense_cents"] == 0
        assert settled["breakeven_cents"] == 1_000_000
        assert settled["artist_base_earnings_cents"] == 1_000_000
        assert settled["artist_coop_contribution_cents"] == 0
        assert settled["artist_earnings_cents"] == 1_000_000
        assert settled["payment_due_cents"] == 1_000_000

        net_before_venue = 390_000 - 1_000_000 - 498_759
        assert net_before_venue == -1_108_759
        assert settled["venue_share_cents"] == apply_pct_to_cents(
            max(0, net_before_venue), 10.00
        ) == 0
        assert settled["promoter_net_cents"] == -1_108_759
        assert settled["adjusted_gross_cents"] == (
            settled["artist_earnings_cents"]
            + settled["promoter_borne_expense_cents"]
            + settled["venue_share_cents"]
            + settled["promoter_net_cents"]
        )


class TestArtistCoopCapKeyedOnTheBase:
    """The cap leg reads the base the previous step produced."""

    def test_cap_leg_binds_and_rounds_half_up_against_the_base_just_produced(
        self, api, build
    ):
        """PRD section 3.7: "the order of its two legs matters because the cap leg is
        keyed on the base the previous step has just produced"

        Design: Difficulty/combinatorial_formula/artist_coop_cap_is_keyed_on_the_base_it_just_produced
        """
        ctx = _coop_leg_shows(build)
        leg = ctx["cap"]

        settled = validate_success(
            api.calculate_settlement(leg["settlement"]["id"], build.accountant)
        )

        assert settled["total_settlement_expense_cents"] == COOP_MARKETING_EXPENSE
        assert settled["artist_base_earnings_cents"] == CAP_BINDING_GUARANTEE == 1_000_010
        # 5 percent of 1,000,010 is exactly 50,000.5 and rounds up in magnitude.
        assert apply_pct_to_cents(CAP_BINDING_GUARANTEE, 5) == 50_001
        assert settled["artist_coop_contribution_cents"] == 50_001
        assert settled["artist_coop_contribution_cents"] < COOP_SHARE_LEG
        assert settled["artist_earnings_cents"] == 1_000_010 - 50_001 == 950_009
        # Keying the cap on artist_earnings_cents instead would have given 47,500.
        assert settled["artist_coop_contribution_cents"] != apply_pct_to_cents(950_009, 5)

    def test_share_leg_binds_when_the_cap_leg_on_a_larger_base_exceeds_it(self, api, build):
        """PRD section 3.7: "The **share leg** is half of that recognised marketing
        expense — 50 percent, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/artist_coop_cap_is_keyed_on_the_base_it_just_produced
        """
        ctx = _coop_leg_shows(build)
        leg = ctx["share"]

        settled = validate_success(
            api.calculate_settlement(leg["settlement"]["id"], build.accountant)
        )

        assert settled["total_settlement_expense_cents"] == COOP_MARKETING_EXPENSE
        assert settled["artist_base_earnings_cents"] == SHARE_BINDING_GUARANTEE == 5_000_000
        assert apply_pct_to_cents(SHARE_BINDING_GUARANTEE, 5) == 250_000
        assert COOP_SHARE_LEG == 100_000
        assert settled["artist_coop_contribution_cents"] == COOP_SHARE_LEG
        assert settled["artist_coop_contribution_cents"] < apply_pct_to_cents(
            SHARE_BINDING_GUARANTEE, 5
        )
        assert settled["artist_earnings_cents"] == 5_000_000 - 100_000 == 4_900_000
        # Keying the cap on artist_earnings_cents instead would have given 245,000.
        assert apply_pct_to_cents(4_900_000, 5) == 245_000

    def test_the_binding_leg_switches_on_the_base_alone(self, api, build):
        """PRD section 3.7: "Which leg binds genuinely varies with the numbers, so
        neither may be assumed."

        Design: Difficulty/combinatorial_formula/artist_coop_cap_is_keyed_on_the_base_it_just_produced
        """
        ctx = _coop_leg_shows(build)

        cap_settled = validate_success(
            api.calculate_settlement(ctx["cap"]["settlement"]["id"], build.accountant)
        )
        share_settled = validate_success(
            api.calculate_settlement(ctx["share"]["settlement"]["id"], build.accountant)
        )

        # Identical recognised marketing expense on both books.
        assert (
            cap_settled["total_settlement_expense_cents"]
            == share_settled["total_settlement_expense_cents"]
            == COOP_MARKETING_EXPENSE
        )
        assert_coop_is_lesser_leg(
            cap_settled["artist_coop_contribution_cents"],
            COOP_MARKETING_EXPENSE,
            cap_settled["artist_base_earnings_cents"],
        )
        assert_coop_is_lesser_leg(
            share_settled["artist_coop_contribution_cents"],
            COOP_MARKETING_EXPENSE,
            share_settled["artist_base_earnings_cents"],
        )
        assert (
            cap_settled["artist_coop_contribution_cents"]
            != share_settled["artist_coop_contribution_cents"]
        )

        for settled, expected_net in (
            (cap_settled, -860_009),
            (share_settled, -4_810_000),
        ):
            assert_waterfall_buckets(settled, COOP_BUCKETS)
            assert settled["adjusted_gross_cents"] == 390_000
            assert settled["venue_expense_reimbursement_cents"] == 0
            assert settled["promoter_borne_expense_cents"] == COOP_MARKETING_EXPENSE
            assert settled["venue_share_cents"] == COOP_RENTAL_FEE
            assert settled["promoter_net_cents"] == expected_net
            assert settled["adjusted_gross_cents"] == (
                settled["artist_earnings_cents"]
                + settled["promoter_borne_expense_cents"]
                + settled["venue_share_cents"]
                + settled["promoter_net_cents"]
            )
