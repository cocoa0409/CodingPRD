"""Forward projection dual variants, marketing CPA rounding, and the tour P&L
computed read (PRD §3.6, §3.8).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_show_with_accepted_hold, create_confirmed_show,
    confirm_show, get_show, get_tour, set_clock,
    create_budget_line_payload, create_marketing_spend_payload,
    update_tickets_payload, assert_show, assert_marketing_spend,
    ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]
PROMOTER = TEST_USERS["promoter_headers"]


def _stage_projected_show(api):
    """One CONFIRMED show (capacity 1000, price 10000) with tickets_sold=400
    and one committed budget line of 200000; logical clock still pre-on-sale."""
    staged = create_staged_tour(
        start_clock="2026-06-01T00:00:00Z",
        tour_overrides={"tour_name": "T1", "window_start_date": "2026-07-15",
                        "window_end_date": "2026-09-01"},
        market_overrides={"market_code": "NYC", "metro_name": "New York",
                          "radius_miles": 60},
        venue_overrides={"venue_name": "MsgHall", "capacity": 1000,
                         "base_rent_cents": 500000,
                         "available_dates": ["2026-08-01"]})
    tid = staged["tour"]["id"]
    show, _ = create_confirmed_show(
        tid, staged["market"]["id"], staged["venue"]["id"],
        show_date="2026-08-01", on_sale_at="2026-07-01T00:00:00Z",
        avg_ticket_price_cents=10000,
        hold_overrides={"guarantee_cents": 500000, "versus_pct": 80})
    validate_success(
        api.update_show_tickets(tid, show["id"],
                                update_tickets_payload(400), PROMOTER), 200)
    # Created while the show is CONFIRMED, so the line is committed (PRD §3.7).
    line = validate_success(
        api.create_budget_line(tid, show["id"],
                               create_budget_line_payload(estimated_cents=200000),
                               TM), 201)
    assert line["is_committed"] is True
    return tid, show["id"]


class TestProjectedPnlPreVsPostOnSale:
    def test_pre_on_sale_variant_values(self, api):
        """PRD §3.8: "While the logical clock is still earlier than the show's
        `on_sale_at`, the pre-on-sale variant projects gross as the frozen
        `capacity` multiplied by `avg_ticket_price_cents` and then by a sellout
        factor of 0.65 — the house is assumed sixty-five percent sold — and
        projects cost as the sum of `estimated_cents` over the show's committed
        budget lines plus 350 cents of per-ticket variable cost for every seat
        of capacity."

        capacity 1000 * price 10000 * 0.65 = 6500000 gross;
        200000 committed estimate + 1000 * 350 = 550000 cost.

        Design: Difficulty/dual_variant_calc/projected_pnl_pre_vs_post_on_sale
        """
        tid, show_id = _stage_projected_show(api)
        show = get_show(tid, show_id)
        assert_show(show)
        assert show["projected_gross_cents"] == 6500000
        assert show["projected_cost_cents"] == 550000

    def test_post_on_sale_variant_values_after_clock_crossing(self, api):
        """PRD §3.8: "Once the clock reaches `on_sale_at`, the post-on-sale
        variant projects gross as the actual `tickets_sold` multiplied by
        `avg_ticket_price_cents`, plus the remaining unsold seats (capacity
        minus tickets sold) multiplied by `avg_ticket_price_cents` and then by
        a decay factor of 0.35, and projects cost as the same
        committed-estimate sum plus 350 cents per ticket actually sold."

        400*10000 + 600*10000*0.35 = 6100000 gross; 200000 + 400*350 = 340000
        cost — the same show with the same tickets_sold projects differently
        before vs after the on-sale crossing.

        Design: Difficulty/dual_variant_calc/projected_pnl_pre_vs_post_on_sale
        """
        tid, show_id = _stage_projected_show(api)
        pre = get_show(tid, show_id)

        set_clock("2026-07-02T00:00:00Z")
        post = get_show(tid, show_id)
        assert post["projected_gross_cents"] == 6100000
        assert post["projected_cost_cents"] == 340000
        assert post["projected_gross_cents"] != pre["projected_gross_cents"], (
            "the two variants diverge on identical show inputs "
            "(6500000 pre vs 6100000 post)")


def _stage_show_for_marketing(api):
    staged = create_staged_tour(
        start_clock="2026-06-01T00:00:00Z",
        tour_overrides={"tour_name": "TM"},
        market_overrides={"market_code": "SEA", "metro_name": "Seattle",
                          "radius_miles": 40},
        venue_overrides={"venue_name": "Paramount", "capacity": 500,
                         "available_dates": ["2026-08-05"]})
    tid = staged["tour"]["id"]
    show = create_show_with_accepted_hold(
        tid, staged["market"]["id"], staged["venue"]["id"],
        show_date="2026-08-05", on_sale_at="2026-07-01T00:00:00Z",
        avg_ticket_price_cents=8000)[0]
    return tid, show["id"]


class TestMarketingCpaPerLineVsBlended:
    def test_per_line_cpa_rounded_half_up_independently(self, api):
        """PRD §3.6: "Each line's `cpa_cents` is its spend divided by its
        attributed sales, rounded half-up to a whole cent". Per-line values are
        computed independently: 500/3 rounds to 167 while 500/4 is exactly 125.

        Design: Difficulty/combinatorial_formula/marketing_cpa_mode_b_per_line_vs_blended
        """
        tid, show_id = _stage_show_for_marketing(api)
        l1 = validate_success(
            api.create_marketing_spend(
                tid, show_id,
                create_marketing_spend_payload(channel="RADIO", spend_cents=500,
                                               attributed_ticket_sales=3),
                TM), 201)
        l2 = validate_success(
            api.create_marketing_spend(
                tid, show_id,
                create_marketing_spend_payload(channel="SOCIAL", spend_cents=500,
                                               attributed_ticket_sales=4),
                TM), 201)
        assert_marketing_spend(l1)
        assert_marketing_spend(l2)
        assert l1["cpa_cents"] == 167, "round_half_up(500/3 = 166.67) = 167"
        assert l2["cpa_cents"] == 125, "round_half_up(500/4 = 125.0) = 125"

    def test_per_line_cpa_independent_across_channels(self, api):
        """PRD §3.6: "Each line's `cpa_cents` is its spend divided by its
        attributed sales, rounded half-up to a whole cent" — each row derives
        from its own spend and sales, unaffected by other rows on the show
        ("The blended figure is always computed from those raw sums — never by
        averaging the individually rounded per-line values.").

        Design: Difficulty/combinatorial_formula/marketing_cpa_mode_b_per_line_vs_blended
        """
        tid, show_id = _stage_show_for_marketing(api)
        l1 = validate_success(
            api.create_marketing_spend(
                tid, show_id,
                create_marketing_spend_payload(channel="OOH", spend_cents=1001,
                                               attributed_ticket_sales=3),
                TM), 201)
        assert l1["cpa_cents"] == 334, "round_half_up(1001/3 = 333.67) = 334"

        l2 = validate_success(
            api.create_marketing_spend(
                tid, show_id,
                create_marketing_spend_payload(channel="INFLUENCER",
                                               spend_cents=1000,
                                               attributed_ticket_sales=6),
                TM), 201)
        assert l2["cpa_cents"] == 167, "round_half_up(1000/6 = 166.67) = 167"

        # Adding the second line does not disturb the first line's own CPA.
        l1_after = validate_success(
            api.get_marketing_spend(tid, show_id, l1["id"], TM), 200)
        assert l1_after["cpa_cents"] == 334


class TestMarketingCpaNull:
    def test_cpa_null_when_no_attributed_sales(self, api):
        """PRD §3.6: "a line with zero attributed sales has a null
        `cpa_cents`."

        Design: Corner/calculations/marketing_cpa_null_when_no_sales
        """
        tid, show_id = _stage_show_for_marketing(api)
        line = validate_success(
            api.create_marketing_spend(
                tid, show_id,
                create_marketing_spend_payload(channel="RADIO", spend_cents=1000,
                                               flight_start_date="2026-06-01",
                                               flight_end_date="2026-07-01",
                                               attributed_ticket_sales=0),
                TM), 201)
        assert_marketing_spend(line)
        assert line["cpa_cents"] is None


class TestTourPnlComputedRead:
    def test_pnl_returns_projected_and_settled_totals(self, api):
        """PRD §3.8: "A computed tour P&L read returns all four totals —
        projected gross, projected cost, settled gross, settled cost — side by
        side." With one CONFIRMED show pre-on-sale: gross 100*10000*0.65 =
        650000; cost 0 committed estimates + 100*350 = 35000; nothing settled.

        Design: Corner/endpoints/get_tour_pnl_computed_read
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"capacity": 100, "available_dates": ["2026-08-01"]})
        tid = staged["tour"]["id"]
        create_confirmed_show(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-01", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=10000,
            hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})

        pnl = validate_success(api.get_tour_pnl(tid, TM), 200)
        assert pnl["projected_gross_cents"] == 650000
        assert pnl["projected_cost_cents"] == 35000
        assert pnl["settled_gross_cents"] == 0
        assert pnl["settled_cost_cents"] == 0
