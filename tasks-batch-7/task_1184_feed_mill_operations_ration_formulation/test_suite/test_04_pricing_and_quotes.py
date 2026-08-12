"""Order pricing: quoted vs final variants, spot tick semantics, contract-blend
projection, quote staleness, and version pinning (PRD §2.7, §2.8, §3.1, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_customer_headers,
    assert_weighment,
    make_ingredient, add_price_tick, make_formula, optimize_formula,
    make_active_formula, make_customer, make_order, confirm_order,
    get_customer, make_employee, make_stocked_bin, make_line, make_batch,
    start_batch, record_weighment, mix_batch, collect_sample,
    enter_sample_result, release_batch, complete_order,
    make_contract, setup_active_grow_formula, setup_batching_batch,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


def _quoted_divergence_setup(api):
    """Catalogue + ACTIVE F-GROW + 10t CONFIRMED order; batch BATCHING; then a
    late corn tick at 31000 lands before weighing (effective 2026-04-15)."""
    ctx = setup_batching_batch(tons=10, credit_limit_cents=1000000)
    # Late-arriving tick: created now, effective in the past, so it reprices
    # the next evaluation while the already-written quote stands (PRD §2.7).
    add_price_tick(ctx["corn"]["id"], 31000, "2026-04-15T00:00:00Z")
    return ctx


class TestQuotedVsFinalDivergence:
    def test_order_quoted_vs_final_price_diverges(self, api):
        """PRD §3.5: "Completion computes the final price, `final_total_cents`, under the same pinned evaluation order as the quote, but with the final variant of line costs: for each ingredient, the sum of `line_cost_cents` over the `RECORDED` weighments of the order's `RELEASED` batches — each already rounded per weighment, and never re-rounded."
        PRD §2.8: "The effective spot price of an ingredient at an instant T is the `price_cents_per_ton` of that ingredient's price tick with the greatest `effective_from` at or before T; when several ticks share that `effective_from`, the one with the latest `created_at` wins."

        Design: Difficulty/dual_variant_calc/order_price_quoted_vs_final_diverges
        """
        ctx = _quoted_divergence_setup(api)
        order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        # Quoted at corn 30000: subtotal 366000, margin 43920, delivery 16500.
        assert order["quoted_total_cents"] == 426420

        # Weigh after the late tick: corn prices at 31000 on the final variant.
        w_corn = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                                  ctx["bin_corn"]["id"], 7.140, ctx["op"]["id"])
        record_weighment(ctx["batch"]["id"], ctx["sbm"]["id"],
                         ctx["bin_sbm"]["id"], 3.000, ctx["op"]["id"])
        batch = mix_batch(ctx["batch"]["id"], ctx["op"]["id"])
        sample = collect_sample(batch["id"], ctx["qt"]["id"])
        enter_sample_result(sample["id"], ctx["qt"]["id"], 19.6, 4.0, 0)
        release_batch(batch["id"], ctx["qt"]["id"])
        order = complete_order(ctx["order"]["id"])

        assert w_corn["unit_price_cents"] == 31000
        assert w_corn["line_cost_cents"] == 221340  # round_half_up(7.140 * 31000)
        # Final: subtotal 221340 + 156000 = 377340; margin 45281; delivery 16500.
        assert order["final_total_cents"] == 439121
        assert order["final_total_cents"] != order["quoted_total_cents"]
        assert order["status"] == "COMPLETED"

    def test_credit_reclasses_to_final_total_on_completion(self, api):
        """PRD §3.5: "The customer's exposure reclasses from the quoted total to the final total, and both versions increment."
        PRD §2.10: "The live exposure, `credit_used_cents`, is the sum of `quoted_total_cents` over the customer's orders in `CONFIRMED` or `IN_PRODUCTION`, plus the sum of `final_total_cents` over the customer's orders in `COMPLETED`."

        Design: Difficulty/dual_variant_calc/order_price_quoted_vs_final_diverges
        """
        ctx = _quoted_divergence_setup(api)
        mid = get_customer(ctx["customer"]["id"])
        assert mid["credit_used_cents"] == 426420, "quoted total charged at confirmation"

        record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                         ctx["bin_corn"]["id"], 7.140, ctx["op"]["id"])
        record_weighment(ctx["batch"]["id"], ctx["sbm"]["id"],
                         ctx["bin_sbm"]["id"], 3.000, ctx["op"]["id"])
        batch = mix_batch(ctx["batch"]["id"], ctx["op"]["id"])
        sample = collect_sample(batch["id"], ctx["qt"]["id"])
        enter_sample_result(sample["id"], ctx["qt"]["id"], 19.6, 4.0, 0)
        release_batch(batch["id"], ctx["qt"]["id"])
        complete_order(ctx["order"]["id"])

        after = get_customer(ctx["customer"]["id"])
        assert after["credit_used_cents"] == 439121, (
            "exposure must reclass from quoted 426420 to final 439121 at completion")


class TestSpotTickSemantics:
    def test_price_tie_break_latest_created_tick_wins(self, api):
        """PRD §2.8: "The effective spot price of an ingredient at an instant T is the `price_cents_per_ton` of that ingredient's price tick with the greatest `effective_from` at or before T; when several ticks share that `effective_from`, the one with the latest `created_at` wins."

        Design: Corner/calculations/price_tie_break_latest_created_tick_wins
        """
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        add_price_tick(corn["id"], 30000, "2026-04-01T00:00:00Z")
        add_price_tick(corn["id"], 31000, "2026-04-01T00:00:00Z")  # same instant, created later
        add_price_tick(sbm["id"], 52000)
        formula = make_formula("F-TIE", min_protein_pct=19.5,
                               max_fiber_pct=5.0, min_energy_kcal_kg=3000)
        solved = optimize_formula(formula)
        # Later-created 31000 tick wins: 0.7 * 31000 + 0.3 * 52000 = 37300.
        assert solved["provisional_cost_cents_per_ton"] == 37300

    def test_late_tick_reprices_formula_and_stales_quote(self, api):
        """PRD §3.1: "Recording a tick is never a quiet event: the provisional cost of every `DRAFT` or `ACTIVE` formula containing that ingredient is recomputed at once."
        PRD §3.5: "`quote_stale` is true exactly when the formula's current `version` differs from `quoted_formula_version` or its current `provisional_cost_cents_per_ton` differs from `quoted_cost_basis_cents`."
        PRD §3.5: "the quote must be fresh (`ERR_QUOTE_STALE`)"

        Design: Corner/calculations/late_tick_reprices_formula_and_stales_quote
        """
        env = setup_active_grow_formula()
        customer = make_customer("Acme Farms", 1000000)
        order = make_order(customer, env["formula"]["id"], 10)  # QUOTED at 36600 basis

        # Late-arriving tick (effective in the past, created after the quote).
        add_price_tick(env["corn"]["id"], 31000, "2026-04-15T00:00:00Z")

        formula = validate_success(api.get_formula(env["formula"]["id"], NUT), 200)
        assert formula["provisional_cost_cents_per_ton"] == 37300

        order = validate_success(
            api.get_order(order["id"], make_customer_headers(customer["id"])), 200)
        assert order["quote_stale"] is True, "cost basis moved 36600 -> 37300"

        resp = api.confirm_order(order["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_STALE)


class TestContractBlendSelector:
    def test_contract_selector_use_it_or_lose_it_ordering(self, api):
        """PRD §2.8: "The pool is always consumed in the same order: earliest `window_end_date` first (use-it-or-lose-it), ties broken toward the lower `fixed_price_cents_per_ton`, further ties toward the earlier `created_at`."
        PRD §3.6: "When the pool is non-empty the weighment takes `source` `CONTRACT` with `contract_id` set and `unit_price_cents` at the contract's fixed price"

        Design: Corner/calculations/contract_selector_use_it_or_lose_it_ordering
        """
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        add_price_tick(corn["id"], 30000)
        add_price_tick(sbm["id"], 52000)
        c1 = make_contract(corn["id"], supplier_ref="SUP-C1",
                           fixed_price_cents_per_ton=29500, total_tons=50,
                           window_start_date="2026-04-01", window_end_date="2026-05-31")
        c2 = make_contract(corn["id"], supplier_ref="SUP-C2",
                           fixed_price_cents_per_ton=29000, total_tons=50,
                           window_start_date="2026-06-01", window_end_date="2026-06-30")
        formula = make_active_formula("F-GROW")
        customer = make_customer("Acme Farms", 1000000)
        order = make_order(customer, formula["id"], 10)
        order = confirm_order(order, customer["id"])
        op = make_employee("Olly Operator", "OPERATOR")
        line = make_line("L1")
        bin_corn = make_stocked_bin("BIN-C", corn["id"], 20)
        batch = make_batch(order["id"], line["id"], 10)
        start_batch(batch["id"], op["id"])

        w = record_weighment(batch["id"], corn["id"], bin_corn["id"], 4.000, op["id"])
        assert_weighment(w)
        # C1 expires first and covers the whole draw, so C1 wins over cheaper C2.
        assert w["source"] == "CONTRACT"
        assert w["contract_id"] == c1["id"]
        assert w["unit_price_cents"] == 29500

        c1_after = validate_success(api.get_contract(c1["id"], MM), 200)
        c2_after = validate_success(api.get_contract(c2["id"], MM), 200)
        assert c1_after["consumed_tons"] == pytest.approx(4.000, abs=1e-6)
        assert c2_after["consumed_tons"] == pytest.approx(0.0, abs=1e-6)

    def test_contract_below_weighment_size_falls_back_to_spot(self, api):
        """PRD §3.6: "The pool is every `OPEN` contract of the weighed ingredient whose window covers the current date and whose `remaining_tons` covers the entire `actual_tons`; a contract whose remaining tonnage exactly equals the draw is selected and is driven to exhaustion by it."
        PRD §3.6: "otherwise it takes `source` `SPOT` with `contract_id` null and `unit_price_cents` at the effective spot price."

        Design: Corner/calculations/contract_below_weighment_size_falls_back_to_spot
        """
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        add_price_tick(corn["id"], 30000)
        add_price_tick(sbm["id"], 52000)
        contract = make_contract(corn["id"], supplier_ref="SUP-TINY",
                                 fixed_price_cents_per_ton=29000, total_tons=2.000,
                                 window_start_date="2026-04-01", window_end_date="2026-06-30")
        formula = make_active_formula("F-GROW")
        customer = make_customer("Acme Farms", 1000000)
        order = make_order(customer, formula["id"], 10)
        order = confirm_order(order, customer["id"])
        op = make_employee("Olly Operator", "OPERATOR")
        line = make_line("L1")
        bin_corn = make_stocked_bin("BIN-C", corn["id"], 20)
        batch = make_batch(order["id"], line["id"], 10)
        start_batch(batch["id"], op["id"])

        # 2.000t remaining cannot cover a 4.000t draw: all-or-nothing per weighment.
        w = record_weighment(batch["id"], corn["id"], bin_corn["id"], 4.000, op["id"])
        assert w["source"] == "SPOT"
        assert w["contract_id"] is None
        assert w["unit_price_cents"] == 30000
        assert w["line_cost_cents"] == 120000  # 4.000 * 30000

        c_after = validate_success(api.get_contract(contract["id"], MM), 200)
        assert c_after["consumed_tons"] == pytest.approx(0.0, abs=1e-6)


class TestVersionPinningOnConfirm:
    def test_version_pinning_confirm_snapshot_survives_reoptimize(self, api):
        """PRD §3.5: "On success the order pins the formula snapshot — `pinned_formula_version`, a deep copy of the lines in `pinned_lines`, and the nutrient floors `pinned_min_protein_pct` and `pinned_max_fiber_pct` — the quoted total joins the customer's exposure, and both the customer's and the order's `version` increment."
        PRD §2.7: "Once persisted, no derived money figure ever changes retroactively: a late-arriving price tick or a contract event takes effect on the next evaluation only, and already-recorded weighment costs and quoted or final order totals stand as written."

        Design: Corner/cross_cutting_complexity_layers/version_pinning_confirm_snapshot_survives_reoptimize
        """
        env = setup_active_grow_formula()
        formula = env["formula"]
        customer = make_customer("Acme Farms", 1000000)
        order = make_order(customer, formula["id"], 10)

        pinned_version = validate_success(
            api.get_formula(formula["id"], NUT), 200)["version"]
        order = confirm_order(order, customer["id"])
        assert order["pinned_formula_version"] == pinned_version
        pinned_lines = [(l["ingredient_id"], l["inclusion_pct"]) for l in order["pinned_lines"]]
        assert pinned_lines == [(env["corn"]["id"], 70), (env["sbm"]["id"], 30)]
        assert order["pinned_min_protein_pct"] == pytest.approx(19.5)
        assert order["pinned_max_fiber_pct"] == pytest.approx(5.0)
        assert order["quoted_total_cents"] == 426420

        # Market moves; the formula is re-optimized (version bumps again).
        add_price_tick(env["corn"]["id"], 31000, "2026-04-15T00:00:00Z")
        fresh = validate_success(api.get_formula(formula["id"], NUT), 200)
        solved = optimize_formula(fresh)
        assert solved["version"] == fresh["version"] + 1
        assert solved["provisional_cost_cents_per_ton"] == 37300

        # The confirmed order keeps its snapshot and quoted price untouched.
        order_after = validate_success(api.get_order(order["id"], MM), 200)
        assert order_after["pinned_formula_version"] == pinned_version
        assert [(l["ingredient_id"], l["inclusion_pct"]) for l in order_after["pinned_lines"]] == \
            [(env["corn"]["id"], 70), (env["sbm"]["id"], 30)]
        assert order_after["quoted_total_cents"] == 426420
