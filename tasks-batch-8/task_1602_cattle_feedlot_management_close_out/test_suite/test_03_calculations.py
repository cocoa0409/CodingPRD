"""Calculation rules: feed cost allocation rounding order, hedge P&L by side,
withdrawal clear-date aggregation, yardage half-open day counting, and hedge
expiry settlement."""
from test_helpers import (
    TEST_USERS,
    choice_carcasses,
    confirm_close_out,
    create_draft_close_out,
    create_hedge,
    create_lot,
    create_owner,
    get_lot,
    list_lot_health_events,
    list_lot_hedges,
    list_lot_invoices,
    offset_hedge,
    post_first_feed_call,
    post_next_feed_call,
    record_health_event,
    set_clock,
    setup_commingled_pen,
    setup_shipped_lot,
)

ANY = TEST_USERS["any_headers"]


class TestFeedCostAllocation:
    def test_feed_cost_split_two_lots_residual_to_latest(self, api):
        """PRD §3.3: "The call's `total_cost_cents` is distributed across the
        pen's `ACTIVE` pen assignments in proportion to each assignment's
        `head_count`, processing assignments in `created_at` ascending order.
        Every assignment except the last in that order receives a share of the
        total proportional to its head, rounded half up to whole cents; the
        last-created assignment receives the residual — the total minus the sum
        of the prior rounded shares."
        PRD §3.3: "a score of 1 adds a quarter pound"

        Design: Corner/calculations/feed_cost_split_two_lots_residual_to_latest
        """
        ws = setup_commingled_pen(
            pen_code="T-60", ration_name="R-C60",
            ration_cost_per_ton_cents=19999, owner_name="O-C60",
            lot_specs=[
                {"lot_number": "L-C60", "head_count_in": 60,
                 "in_weight_total_lbs": 42000, "purchase_cost_cents": 8400000},
                {"lot_number": "L-C40", "head_count_in": 40,
                 "in_weight_total_lbs": 28000, "purchase_cost_cents": 5600000},
            ],
        )
        post_first_feed_call(ws["pen"]["id"], "2026-08-01", 10.0)
        second = post_next_feed_call(ws["pen"]["id"], "2026-08-02", 1)
        assert second["total_cost_cents"] == 10299, (
            "10.25 -> 10.3 lbs/head x 100 head = 1030 lbs; "
            "0.515 t x 19999 = 10299.485 -> round half up 10299"
        )

        l60 = get_lot(ws["lots"][0]["id"])
        l40 = get_lot(ws["lots"][1]["id"])
        assert l60["total_feed_cost_cents"] == 12179, (
            "6000 from call 1 + round_half_up(10299 x 0.6) = 6179 from call 2"
        )
        assert l40["total_feed_cost_cents"] == 8120, (
            "4000 residual from call 1 + 4120 residual from call 2"
        )
        assert l60["total_feed_cost_cents"] + l40["total_feed_cost_cents"] == 20299, (
            "Allocation conserves every cent: 10000 + 10299"
        )


class TestHedgePnl:
    def test_hedge_pnl_short_and_long(self, api):
        """PRD §3.6: "Realized P&L follows the side: for a `SHORT` position it is
        the entry price minus the exit price, multiplied by the
        400-hundredweight contract size and the number of contracts; for a
        `LONG` position the price difference is reversed. The result is stored
        as `realized_pnl_cents` (which may be negative), added into the lot's
        `total_hedge_pnl_cents`"

        Design: Corner/calculations/hedge_pnl_short_and_long
        """
        owner = create_owner(owner_name="O-HP", billing_email="hp@x.com")
        lot = create_lot(owner["id"], lot_number="L-HP", head_count_in=80,
                         in_weight_total_lbs=80000, purchase_cost_cents=9600000)
        h1 = create_hedge(lot["id"], lot["version"], side="SHORT",
                          quantity_contracts=2, entry_price_cents_per_cwt=19000)
        h2 = create_hedge(lot["id"], get_lot(lot["id"])["version"], side="LONG",
                          quantity_contracts=1, entry_price_cents_per_cwt=18500)

        off1 = offset_hedge(h1["id"], 18500, offset_date="2026-08-01")
        assert off1["realized_pnl_cents"] == 400000, (
            "SHORT: (19000 - 18500) x 400 cwt x 2 contracts"
        )
        off2 = offset_hedge(h2["id"], 19000, offset_date="2026-08-01")
        assert off2["realized_pnl_cents"] == 200000, (
            "LONG: (19000 - 18500) x 400 cwt x 1 contract"
        )
        assert get_lot(lot["id"])["total_hedge_pnl_cents"] == 600000

    def test_hedge_expiry_settles_at_entry(self, api):
        """PRD §3.6: "when the logical date reaches the first day of the
        `contract_month`, the position moves `OPEN → EXPIRED`, settling at its
        entry price with `realized_pnl_cents` of zero and leaving the lot's P&L
        unchanged."

        Design: Corner/calculations/hedge_expiry_settles_at_entry
        """
        owner = create_owner(owner_name="O-HE", billing_email="he@x.com")
        lot = create_lot(owner["id"], lot_number="L-HE", head_count_in=80,
                         in_weight_total_lbs=80000, purchase_cost_cents=9600000)
        create_hedge(lot["id"], lot["version"], contract_month="2026-09",
                     quantity_contracts=1, entry_price_cents_per_cwt=19000)

        set_clock("2026-08-15T00:00:00Z")
        hedges = list_lot_hedges(lot["id"])
        assert hedges[0]["status"] == "OPEN", (
            "2026-08-15 is before the 2026-09 contract month"
        )

        set_clock("2026-09-01T00:00:00Z")
        hedges = list_lot_hedges(lot["id"])
        assert hedges[0]["status"] == "EXPIRED"
        assert hedges[0]["realized_pnl_cents"] == 0
        assert hedges[0]["exit_price_cents_per_cwt"] == 19000, (
            "Expiry settles at the entry price"
        )
        assert get_lot(lot["id"])["total_hedge_pnl_cents"] == 0


class TestWithdrawalClearDate:
    def test_withdrawal_clear_date_max_and_clock_clear(self, api):
        """PRD §3.4: "recomputes the lot's `withdrawal_clear_date` as the latest
        `withdrawal_end_date` across all of the lot's health events"
        PRD §2.5: "Every health event whose `withdrawal_end_date` is on or before
        the new date transitions from `WITHDRAWAL_ACTIVE` to `CLEARED`."

        Design: Corner/calculations/withdrawal_clear_date_max_and_clock_clear
        """
        owner = create_owner(owner_name="O-WD", billing_email="wd@x.com")
        lot = create_lot(owner["id"], lot_number="L-WD", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        record_health_event(lot["id"], treatment_date="2026-08-01",
                            drug_product="DRAXXIN", withdrawal_days=5,
                            head_treated=1, treatment_cost_cents=1000)
        record_health_event(lot["id"], treatment_date="2026-08-01",
                            drug_product="BAYTRIL", withdrawal_days=12,
                            head_treated=1, treatment_cost_cents=1500)

        assert get_lot(lot["id"])["withdrawal_clear_date"] == "2026-08-13", (
            "The clear date is the max over all events, not the earliest"
        )

        set_clock("2026-08-07T00:00:00Z")
        events = list_lot_health_events(lot["id"])
        assert events[0]["status"] == "CLEARED", "End 2026-08-06 is past"
        assert events[1]["status"] == "WITHDRAWAL_ACTIVE", (
            "End 2026-08-13 is still in the future"
        )

        set_clock("2026-08-13T00:00:00Z")
        events = list_lot_health_events(lot["id"])
        assert events[0]["status"] == "CLEARED"
        assert events[1]["status"] == "CLEARED", (
            "An event clears ON its withdrawal end date"
        )


class TestYardage:
    def test_yardage_simple_half_open_counting(self, api):
        """PRD §3.7: "For the final variant the window runs from `arrival_date`
        up to but not including the ship date; `yardage_cents` is the resulting
        head-days multiplied by the yardage rate of 45 cents per head-day."

        Design: Corner/calculations/yardage_simple_half_open_counting
        """
        ws = setup_shipped_lot(
            owner_name="O-YD", pen_code="Y-01", lot_number="L-YD",
            head_count_in=10, in_weight_total_lbs=7000,
            purchase_cost_cents=1400000, head_assigned=10,
            clock_to="2026-08-05T00:00:00Z", ship_date="2026-08-05",
            out_weight_total_lbs=7500,
        )
        close_out = create_draft_close_out(ws["lot"]["id"], ws["lot_version"])
        confirm_close_out(close_out["id"], choice_carcasses(10, 465))

        invoice = list_lot_invoices(ws["lot"]["id"])[0]
        assert invoice["yardage_head_days"] == 40, (
            "[2026-08-01, 2026-08-05) is 4 billable days x 10 head; the ship day "
            "is excluded"
        )
        assert invoice["yardage_cents"] == 1800, "40 head-days x 45 cents"
