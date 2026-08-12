"""Transitive cascades: sample-FAIL detonation and contract exhaustion (PRD §3.2, §3.5, §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers, make_operator_headers,
    assert_weighment, make_active_formula, mix_batch,
    setup_mixed_batch, setup_confirmed_order, setup_batching_batch,
    setup_active_grow_formula,
    make_ingredient, add_price_tick, make_contract, make_customer, make_order,
    confirm_order, get_customer, make_employee, make_stocked_bin, make_line,
    make_batch, start_batch, record_weighment, collect_sample,
    enter_sample_result, make_truck, create_trip_payload,
)

MM = TEST_USERS["mill_manager_headers"]


class TestSampleFailCascade:
    def test_sample_fail_puts_batch_on_hold_and_blocks_order(self, api):
        """PRD §3.8: "A failing sample moves `PENDING` → `FAIL` and detonates a cascade in the same request: the batch moves `MIXED` → `HOLD`, the order's `blocked` recomputes to true, and every delivery trip of the order in `PLANNED` or `LOADING` is cancelled with its compartment allocations released — cancelled trips are not auto-revived if the batch later recovers."

        Design: Difficulty/transitive_cascade/sample_fail_cascades_batch_hold_order_blocked_trips_cancelled
        """
        ctx = setup_mixed_batch()
        sample = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])
        # Dry-matter protein 17.0 < pinned floor 19.5 -> FAIL.
        failed = enter_sample_result(sample["id"], ctx["qt"]["id"], 17.0, 4.0, 0)
        assert failed["result"] == "FAIL"

        batch = validate_success(api.get_batch(ctx["batch"]["id"], MM), 200)
        assert batch["status"] == "HOLD", "hop 1: FAIL moves the batch MIXED -> HOLD"

        order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert order["blocked"] is True, "hop 2: the derived blocked flag recomputes"

    def test_sample_fail_cancels_planned_trips(self, api):
        """PRD §3.8: "A failing sample moves `PENDING` → `FAIL` and detonates a cascade in the same request: the batch moves `MIXED` → `HOLD`, the order's `blocked` recomputes to true, and every delivery trip of the order in `PLANNED` or `LOADING` is cancelled with its compartment allocations released — cancelled trips are not auto-revived if the batch later recovers."
        PRD §3.5: "The order's `blocked` flag, used by several gates above, is derived: true exactly when any batch of the order sits in `HOLD`."

        Design: Difficulty/transitive_cascade/sample_fail_cascades_batch_hold_order_blocked_trips_cancelled
        """
        ctx = setup_mixed_batch()
        # Trip creation is legal while the order is IN_PRODUCTION and not blocked.
        truck = make_truck("TRK-01", "STANDARD_ONLY",
                           [{"compartment_seq": 1, "capacity_tons": 12}])
        trip = get_success_data(api.create_trip(
            create_trip_payload(truck["id"], ctx["order"]["id"]), MM))
        assert trip["status"] == "PLANNED"

        sample = collect_sample(ctx["batch"]["id"], ctx["qt"]["id"])
        enter_sample_result(sample["id"], ctx["qt"]["id"], 17.0, 4.0, 0)

        trip_after = validate_success(api.get_trip(trip["id"], MM), 200)
        assert trip_after["status"] == "CANCELLED", (
            "hop 3: every PLANNED/LOADING trip of the blocked order is cancelled")

        order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert order["status"] == "IN_PRODUCTION", (
            "blocked is a derived flag, not an order state")


class TestContractExhaustionCascade:
    def _exhaustion_setup(self, api):
        """Corn contract of exactly 7.140t @ 29000; F-GROW ACTIVE with a
        contract-blended provisional cost of 35900; order1 CONFIRMED, order2
        still QUOTED; order1's batch BATCHING."""
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        add_price_tick(corn["id"], 30000)
        add_price_tick(sbm["id"], 52000)
        contract = make_contract(corn["id"], supplier_ref="SUP-1",
                                 fixed_price_cents_per_ton=29000, total_tons=7.140,
                                 window_start_date="2026-04-01",
                                 window_end_date="2026-06-30")
        formula = make_active_formula("F-GROW")
        assert formula["provisional_cost_cents_per_ton"] == 35900, (
            "contract blend: 0.7t @ 29000 + 0.3t @ 52000")

        customer = make_customer("Acme Farms", 5000000)
        order1 = make_order(customer, formula["id"], 10)
        order1 = confirm_order(order1, customer["id"])
        order2 = make_order(customer, formula["id"], 10)  # stays QUOTED

        op = make_employee("Olly Operator", "OPERATOR")
        line = make_line("L1")
        bin_corn = make_stocked_bin("BIN-C", corn["id"], 20)
        bin_sbm = make_stocked_bin("BIN-S", sbm["id"], 20)
        batch = make_batch(order1["id"], line["id"], 10)
        start_batch(batch["id"], op["id"])
        return {"corn": corn, "sbm": sbm, "contract": contract, "formula": formula,
                "customer": customer, "order1": order1, "order2": order2,
                "op": op, "batch": batch, "bin_corn": bin_corn, "bin_sbm": bin_sbm}

    def test_weighment_exhausts_contract_at_exact_boundary(self, api):
        """PRD §3.6: "a contract whose remaining tonnage exactly equals the draw is selected and is driven to exhaustion by it."
        PRD §3.2: "When a recorded weighment drives `remaining_tons` to exactly zero, the contract moves `OPEN` → `EXHAUSTED` on its own: it leaves the pricing selector pool, the provisional cost of every affected formula is recomputed, and customer orders still `QUOTED` against those formulas flip their derived `quote_stale` flag to true."

        Design: Difficulty/transitive_cascade/contract_exhaustion_cascades_formula_recompute_quote_stale
        """
        ctx = self._exhaustion_setup(api)
        # Full-coverage boundary: remaining 7.140 == actual 7.140 -> CONTRACT.
        w = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                             ctx["bin_corn"]["id"], 7.140, ctx["op"]["id"])
        assert_weighment(w)
        assert w["source"] == "CONTRACT"
        assert w["contract_id"] == ctx["contract"]["id"]
        assert w["unit_price_cents"] == 29000
        assert w["line_cost_cents"] == 207060  # 7.140 * 29000

        contract = validate_success(api.get_contract(ctx["contract"]["id"], MM), 200)
        assert contract["status"] == "EXHAUSTED", "hop 2: remaining hit exactly zero"
        assert contract["remaining_tons"] == pytest.approx(0.0, abs=1e-6)
        assert contract["consumed_tons"] == pytest.approx(7.140, abs=1e-6)

    def test_exhaustion_recomputes_formula_and_stales_quote(self, api):
        """PRD §3.2: "When a recorded weighment drives `remaining_tons` to exactly zero, the contract moves `OPEN` → `EXHAUSTED` on its own: it leaves the pricing selector pool, the provisional cost of every affected formula is recomputed, and customer orders still `QUOTED` against those formulas flip their derived `quote_stale` flag to true."
        PRD §3.5: "the quote must be fresh (`ERR_QUOTE_STALE`)"

        Design: Difficulty/transitive_cascade/contract_exhaustion_cascades_formula_recompute_quote_stale
        """
        ctx = self._exhaustion_setup(api)
        record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                         ctx["bin_corn"]["id"], 7.140, ctx["op"]["id"])

        formula = validate_success(api.get_formula(ctx["formula"]["id"], MM), 200)
        # hop 3: spot-only after the contract left the pool (35900 -> 36600).
        assert formula["provisional_cost_cents_per_ton"] == 36600

        order2 = validate_success(api.get_order(ctx["order2"]["id"], MM), 200)
        assert order2["quote_stale"] is True, "hop 4: the cost basis moved"

        resp = api.confirm_order(
            ctx["order2"]["id"], make_customer_headers(ctx["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_QUOTE_STALE)

        # The pinned, CONFIRMED order1 is unaffected by the cascade.
        order1 = validate_success(api.get_order(ctx["order1"]["id"], MM), 200)
        assert order1["quoted_total_cents"] == 418580


class TestOrderBlockedGates:
    def test_order_blocked_gates_batch_start_and_trip_create(self, api):
        """PRD §3.6: "the order must not be `blocked` (`ERR_ORDER_BLOCKED`); and the sequencing gate — a batch whose `is_medicated` is false may not start on a line whose `contamination` is `MEDICATED` unless a `VERIFIED` flush exists whose `verified_at` falls after the last medicated batch's `mixed_at` (`ERR_FLUSH_REQUIRED`)."
        PRD §3.9: "The order must be `IN_PRODUCTION` or `COMPLETED` — anything earlier surfaces `ERR_INVALID_STATE` — and must not be `blocked` (`ERR_ORDER_BLOCKED`)."

        Design: Corner/errors/order_blocked_gates_batch_start_and_trip_create
        """
        ctx = setup_confirmed_order(tons=10, credit_limit_cents=1000000)
        op = make_employee("Olly Operator", "OPERATOR")
        qt = make_employee("Quinn Quality", "QUALITY_TECH")
        line = make_line("L1")
        bin_corn = make_stocked_bin("BIN-C", ctx["corn"]["id"], 20)
        bin_sbm = make_stocked_bin("BIN-S", ctx["sbm"]["id"], 20)
        bat1 = make_batch(ctx["order"]["id"], line["id"], 5,
                          "2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z")
        bat2 = make_batch(ctx["order"]["id"], line["id"], 5,
                          "2026-05-02T12:00:00Z", "2026-05-02T13:00:00Z")
        start_batch(bat1["id"], op["id"])
        record_weighment(bat1["id"], ctx["corn"]["id"], bin_corn["id"], 3.500, op["id"])
        record_weighment(bat1["id"], ctx["sbm"]["id"], bin_sbm["id"], 1.500, op["id"])
        mix_batch(bat1["id"], op["id"])
        # FAIL result -> batch1 HOLD -> order blocked.
        sample = collect_sample(bat1["id"], qt["id"])
        enter_sample_result(sample["id"], qt["id"], 17.0, 4.0, 0)

        order = validate_success(api.get_order(ctx["order"]["id"], MM), 200)
        assert order["blocked"] is True

        # Sibling batch start refused while the order is blocked.
        r1 = api.start_batch(bat2["id"], make_operator_headers(op["id"]))
        validate_error(r1, ApiErrorId.ERR_ORDER_BLOCKED)

        # New trip refused too.
        truck = make_truck("TRK-09", "STANDARD_ONLY",
                           [{"compartment_seq": 1, "capacity_tons": 12}])
        r2 = api.create_trip(create_trip_payload(
            truck["id"], ctx["order"]["id"],
            compartment_allocations=[{"compartment_seq": 1, "tons": 5,
                                      "cargo_class": "STANDARD"}],
            planned_departure_at="2026-05-03T09:00:00Z",
            planned_return_at="2026-05-03T12:00:00Z"), MM)
        validate_error(r2, ApiErrorId.ERR_ORDER_BLOCKED)

        bat2_after = validate_success(api.get_batch(bat2["id"], MM), 200)
        assert bat2_after["status"] == "PLANNED"
