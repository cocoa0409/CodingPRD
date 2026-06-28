"""Commission settlement: gross/clawback/net aggregation, rounding order,
half-open window, input-set filtering, finalize ledger sync, OCC.

Covers difficulty dual_variant_calc (settlement), combinatorial_formula (rounding),
resource_temporal_overlap (half-open window), and several corner instances.
"""
from test_helpers import (
    api_client, validate_success, validate_error, officer_headers,
    setup_window_with_sold_tickets, fresh_retailer_version, create_settlement,
    create_settlement_payload, sell_and_counter_pay, set_clock, ApiErrorId,
    create_game, setup_active_retailer_with_terminal, sell_ticket,
)


class TestSettlementAggregation:
    def test_net_floors_at_zero_when_clawback_exceeds_gross(self, api):
        """PRD 3.8: "`net_settlement_cents` is `gross_commission_cents` minus
        `clawback_cents`, floored at 0: a retailer is never billed a negative settlement."

        Design: Difficulty/dual_variant_calc/settlement_net_floor_vs_gross_on_retailer_ledger
        """
        game = create_game(game_type="INSTANT", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal(
            retailer_overrides={"commission_rate": 0.06, "cashing_bonus_rate": 0.01})
        set_clock("2026-03-15T00:00:00Z")
        # one plain sold ticket price 100 (tier 0)
        sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-03-15T00:00:00Z")
        # one counter-paid ticket gross_prize 50,000 (+500 bonus) then reversed (clawback 500)
        rev = sell_and_counter_pay(game["id"], term["id"], gross_prize_cents=50000,
                                   draw_date="2026-03-16T00:00:00Z", price_cents=100)
        validate_success(api.reverse_counter_pay(rev["id"], officer_headers("u-officer")))
        rv = fresh_retailer_version(ret["id"])
        payload = create_settlement_payload(
            ret["id"], "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", rv)
        data = validate_success(
            api.create_settlement(payload, officer_headers("u-prep")), expected_status=201)
        assert data["gross_commission_cents"] == 12, data["gross_commission_cents"]
        assert data["clawback_cents"] == 500, data["clawback_cents"]
        assert data["net_settlement_cents"] == 0, data["net_settlement_cents"]

    def test_clawback_aggregates_counter_reversed_bonus(self, api):
        """PRD 3.8: "the settlement's `clawback_cents` is the sum, over window tickets
        whose `validation_status` is `COUNTER_REVERSED`, of each such ticket's
        `gross_prize_cents` times the retailer's `cashing_bonus_rate` rounded half-up to
        the nearest cent"

        Design: Difficulty/dual_variant_calc/settlement_net_floor_vs_gross_on_retailer_ledger
        """
        game = create_game(game_type="INSTANT", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal(
            retailer_overrides={"commission_rate": 0.06, "cashing_bonus_rate": 0.01})
        set_clock("2026-03-15T00:00:00Z")
        sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-03-15T00:00:00Z")
        rev = sell_and_counter_pay(game["id"], term["id"], gross_prize_cents=50000,
                                   draw_date="2026-03-16T00:00:00Z", price_cents=100)
        validate_success(api.reverse_counter_pay(rev["id"], officer_headers("u-officer")))
        rv = fresh_retailer_version(ret["id"])
        payload = create_settlement_payload(
            ret["id"], "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z", rv)
        data = validate_success(
            api.create_settlement(payload, officer_headers("u-prep")), expected_status=201)
        # 50000 * 0.01 = 500, the bonus accrued then reversed within the window
        assert data["clawback_cents"] == 500, data["clawback_cents"]

    def test_sales_commission_rounds_once_on_summed_base(self, api):
        """PRD 3.8: "sums their `price_cents`, multiplies that single summed base by the
        retailer's `commission_rate`, and rounds the product half-up exactly once (sum
        first, then round)."

        Design: Difficulty/combinatorial_formula/settlement_mixed_rounding_order_sum_then_round_vs_round_then_sum
        """
        game, ret, term, tickets = setup_window_with_sold_tickets(
            prices=[125, 125, 125], game_type="DAILY", commission_rate=0.06,
            cashing_bonus_rate=0.01, clock="2026-05-10T00:00:00Z",
            draw_date="2026-05-10T00:00:00Z")
        rv = fresh_retailer_version(ret["id"])
        payload = create_settlement_payload(
            ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", rv)
        data = validate_success(
            api.create_settlement(payload, officer_headers("u-prep")), expected_status=201)
        # 375 * 0.06 = 22.5 -> round-half-up 23 (NOT 8+8+8=24)
        assert data["gross_commission_cents"] == 23, data["gross_commission_cents"]
        assert data["clawback_cents"] == 0
        assert data["net_settlement_cents"] == 23

    def test_net_equals_gross_when_no_clawback(self, api):
        """PRD 3.8: "Finally, `net_settlement_cents` is `gross_commission_cents` minus
        `clawback_cents`, floored at 0"

        Design: Difficulty/combinatorial_formula/settlement_mixed_rounding_order_sum_then_round_vs_round_then_sum
        """
        game, ret, term, tickets = setup_window_with_sold_tickets(
            prices=[125, 125, 125], game_type="DAILY", commission_rate=0.06,
            cashing_bonus_rate=0.01, clock="2026-05-10T00:00:00Z",
            draw_date="2026-05-10T00:00:00Z")
        rv = fresh_retailer_version(ret["id"])
        payload = create_settlement_payload(
            ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", rv)
        data = validate_success(
            api.create_settlement(payload, officer_headers("u-prep")), expected_status=201)
        # no counter-pays/clawbacks -> net == gross == 23
        assert data["net_settlement_cents"] == data["gross_commission_cents"] == 23


class TestSettlementWindow:
    def test_half_open_window_excludes_period_end_ticket(self, api):
        """PRD 3.8: "The window is the half-open interval from `period_start` up to but
        not including `period_end`, and the source rows are all tickets sold by terminals
        that this retailer owns whose `created_at` falls within that interval."

        Design: Difficulty/resource_temporal_overlap/settlement_window_half_open_excludes_period_end_ticket
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal(
            retailer_overrides={"commission_rate": 0.06})
        set_clock("2026-05-01T00:00:00Z")
        sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-05-01T00:00:00Z")  # included
        set_clock("2026-06-01T00:00:00Z")
        sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-06-01T00:00:00Z")  # excluded (== period_end)
        rv = fresh_retailer_version(ret["id"])
        payload = create_settlement_payload(
            ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", rv)
        data = validate_success(
            api.create_settlement(payload, officer_headers("u-prep")), expected_status=201)
        # only the period_start ticket counts: 100 * 0.06 = 6
        assert data["gross_commission_cents"] == 6, data["gross_commission_cents"]

    def test_period_start_ticket_is_included(self, api):
        """PRD 3.8: "The window is the half-open interval from `period_start` up to but
        not including `period_end`"

        Design: Difficulty/resource_temporal_overlap/settlement_window_half_open_excludes_period_end_ticket
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        ret, term = setup_active_retailer_with_terminal(
            retailer_overrides={"commission_rate": 0.06})
        set_clock("2026-05-01T00:00:00Z")  # == period_start (inclusive)
        sell_ticket(game["id"], term["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-05-01T00:00:00Z")
        rv = fresh_retailer_version(ret["id"])
        payload = create_settlement_payload(
            ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", rv)
        data = validate_success(
            api.create_settlement(payload, officer_headers("u-prep")), expected_status=201)
        # the period_start ticket IS counted: 100 * 0.06 = 6
        assert data["gross_commission_cents"] == 6, data["gross_commission_cents"]

    def test_settlement_excludes_other_retailers_tickets(self, api):
        """PRD 3.8: "the source rows are all tickets sold by terminals that this retailer
        owns whose `created_at` falls within that interval."

        Design: Corner/calculations/settlement_input_set_excludes_other_retailer_tickets
        """
        game = create_game(game_type="DAILY", federal_withholding_threshold_cents=600000)
        retA, termA = setup_active_retailer_with_terminal(
            retailer_overrides={"commission_rate": 0.06})
        retB, termB = setup_active_retailer_with_terminal(
            retailer_overrides={"commission_rate": 0.06})
        set_clock("2026-05-10T00:00:00Z")
        sell_ticket(game["id"], termA["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-05-10T00:00:00Z")
        sell_ticket(game["id"], termB["id"], declared_tier=0, gross_prize_cents=0,
                    price_cents=100, draw_date="2026-05-10T00:00:00Z")
        rv = fresh_retailer_version(retA["id"])
        payload = create_settlement_payload(
            retA["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", rv)
        data = validate_success(
            api.create_settlement(payload, officer_headers("u-prep")), expected_status=201)
        assert data["gross_commission_cents"] == 6, data["gross_commission_cents"]


class TestSettlementFinalize:
    def test_finalize_debits_balance_and_credits_lifetime(self, api):
        """PRD 3.8: "the retailer's `commission_balance_cents` is reduced by the
        settlement's `net_settlement_cents` and the retailer's `lifetime_settled_cents`
        is increased by the same `net_settlement_cents`."

        Design: Corner/calculations/finalize_settlement_debits_and_credits_ledger
        """
        game, ret, term, tickets = setup_window_with_sold_tickets(
            prices=[100], game_type="DAILY", commission_rate=0.06,
            clock="2026-05-10T00:00:00Z", draw_date="2026-05-10T00:00:00Z")
        st = create_settlement(ret["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z",
                               prep_user_id="u-prep")
        data = validate_success(api.finalize_settlement(st["id"], officer_headers("u-appr")))
        assert data["status"] == "FINALIZED", data["status"]
        r = validate_success(api.get_retailer(ret["id"], officer_headers("u-officer")))
        assert r["lifetime_settled_cents"] == 6, r["lifetime_settled_cents"]
        assert r["commission_balance_cents"] == 0, r["commission_balance_cents"]
