"""Bin administration, contract lifecycle, formula retirement, and the
compensating conservation invariants (PRD §3.1-§3.4, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_bin, assert_contract, assert_weighment,
    make_ingredient, add_price_tick, make_contract, make_bin,
    make_stocked_bin, make_customer, make_order, confirm_order,
    make_employee, make_line, make_batch, start_batch, record_weighment,
    setup_batching_batch, setup_confirmed_order, advance_clock,
    create_bin_payload, create_contract_payload, make_active_formula,
    make_customer_headers, make_operator_headers,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


class TestBinAdminErrors:
    def test_bin_admin_domain_errors(self, api):
        """PRD §3.3: "Assignment is permitted only while `on_hand_tons` is exactly zero — the boundary passes, and any residual stock at all draws `ERR_BIN_NOT_EMPTY`."
        PRD §3.3: "the resulting level must not exceed `capacity_tons`; a replenishment landing exactly on capacity passes, while anything above is rejected with `ERR_BIN_CAPACITY_EXCEEDED`."
        PRD §3.3: "A replenish requires the bin to be assigned and not `BLOCKED` — a blocked bin refuses with `ERR_BIN_BLOCKED` — and the resulting level must not exceed `capacity_tons`"
        PRD §2.11: "Uniqueness, capacity, and constraint checks, evaluated within this layer in exactly this order: duplicate codes (`ERR_DUPLICATE_CODE`)"

        Design: Corner/errors/bin_admin_domain_errors
        """
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        bin_c = make_stocked_bin("BIN-C", corn["id"], 10)  # capacity 50

        # Duplicate bin code.
        r_dup = api.create_bin(create_bin_payload("BIN-C", 30), MM)
        validate_error(r_dup, ApiErrorId.ERR_DUPLICATE_CODE)

        # 10 + 41 > 50 (landing exactly on 50 would pass).
        r_cap = api.replenish_bin(bin_c["id"], {"tons": 41}, MM)
        validate_error(r_cap, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED)

        # Reassignment while stock remains.
        r_ne = api.assign_bin(bin_c["id"], {"ingredient_id": sbm["id"]}, MM)
        validate_error(r_ne, ApiErrorId.ERR_BIN_NOT_EMPTY)

        # Ingredient discontinuation cascades the stocked bin READY -> BLOCKED.
        validate_success(api.discontinue_ingredient(corn["id"], MM), 200)
        blocked = validate_success(api.get_bin(bin_c["id"], MM), 200)
        assert blocked["status"] == "BLOCKED"

        r_blk = api.replenish_bin(bin_c["id"], {"tons": 1}, MM)
        validate_error(r_blk, ApiErrorId.ERR_BIN_BLOCKED)


class TestContractLifecycle:
    def test_contract_auto_expires_on_clock_sweep(self, api):
        """PRD §2.5: "Advancing the clock triggers the contract expiry sweep: every `OPEN` contract whose window end has passed with tonnage still remaining transitions to `EXPIRED`, and provisional formula costs are recomputed wherever contract selector pools changed."

        Design: Corner/state_machines/contract_auto_expires_on_clock_sweep
        """
        corn = make_ingredient("CORN")
        add_price_tick(corn["id"], 30000)
        contract = make_contract(corn["id"], supplier_ref="SUP-OLD",
                                 fixed_price_cents_per_ton=29000, total_tons=50,
                                 window_start_date="2026-03-01",
                                 window_end_date="2026-04-30")

        # Advance past the window end with all tonnage remaining.
        advance_clock("2026-05-10T00:00:00Z")
        after = validate_success(api.get_contract(contract["id"], MM), 200)
        assert_contract(after)
        assert after["status"] == "EXPIRED"
        assert after["remaining_tons"] == pytest.approx(50, abs=1e-6), (
            "expiry does not consume tonnage")

    def test_contract_window_closed_overlap_rejected(self, api):
        """PRD §3.2: "The overlap test follows closed-interval semantics: a new window whose start date exactly equals an existing window's end date conflicts, and the violation is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`."
        PRD §3.2: "`EXPIRED` and `CANCELLED` contracts do not block new coverage."

        Design: Corner/errors/contract_window_closed_overlap_rejected
        """
        corn = make_ingredient("CORN")
        c1 = make_contract(corn["id"], supplier_ref="SUP-C1",
                           fixed_price_cents_per_ton=29000, total_tons=50,
                           window_start_date="2026-04-01", window_end_date="2026-05-31")
        assert c1["status"] == "OPEN"

        # True overlap: [05-15, 06-30] vs [04-01, 05-31].
        r_ov = api.create_contract(create_contract_payload(
            corn["id"], supplier_ref="SUP-C2", fixed_price_cents_per_ton=29100,
            total_tons=50, window_start_date="2026-05-15",
            window_end_date="2026-06-30"), MM)
        validate_error(r_ov, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)

        # Touching at a single date still conflicts: closed intervals.
        r_touch = api.create_contract(create_contract_payload(
            corn["id"], supplier_ref="SUP-C3", fixed_price_cents_per_ton=29100,
            total_tons=50, window_start_date="2026-05-31",
            window_end_date="2026-06-30"), MM)
        validate_error(r_touch, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP)

        # 06-01 is the first non-conflicting start date.
        c4 = validate_success(api.create_contract(create_contract_payload(
            corn["id"], supplier_ref="SUP-C4", fixed_price_cents_per_ton=29100,
            total_tons=50, window_start_date="2026-06-01",
            window_end_date="2026-06-30"), MM), 201)
        assert c4["status"] == "OPEN"

    def test_contract_for_discontinued_ingredient_rejected(self, api):
        """PRD §3.2: "the ingredient must be `ACTIVE` (a contract for a discontinued ingredient is refused with `ERR_INGREDIENT_NOT_ACTIVE`)"

        Design: Corner/errors/contract_for_discontinued_ingredient_rejected
        """
        corn = make_ingredient("CORN")
        validate_success(api.discontinue_ingredient(corn["id"], MM), 200)

        resp = api.create_contract(create_contract_payload(
            corn["id"], supplier_ref="SUP-X", fixed_price_cents_per_ton=29000,
            total_tons=50, window_start_date="2026-04-01",
            window_end_date="2026-06-30"), MM)
        validate_error(resp, ApiErrorId.ERR_INGREDIENT_NOT_ACTIVE)


class TestFormulaRetireInUse:
    def test_formula_retire_blocked_while_pinned_by_live_order(self, api):
        """PRD §3.4: "Manually retiring an `ACTIVE` formula is refused with `ERR_FORMULA_IN_USE` while any live order — one in `CONFIRMED`, `REVISING`, `IN_PRODUCTION`, or `COMPLETED` — pins it; the ingredient-discontinuation cascade ignores this guard, as §3.1 notes."

        Design: Corner/errors/formula_retire_blocked_while_pinned_by_live_order
        """
        ctx = setup_confirmed_order(tons=10, credit_limit_cents=1000000)
        formula_id = ctx["formula"]["id"]

        # The CONFIRMED order pins the formula.
        resp = api.retire_formula(formula_id, NUT)
        validate_error(resp, ApiErrorId.ERR_FORMULA_IN_USE)

        # Once the order is cancelled, no live order pins it and retire succeeds.
        validate_success(api.cancel_order(
            ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
        retired = validate_success(api.retire_formula(formula_id, NUT), 200)
        assert retired["status"] == "RETIRED"


class TestBinInventoryInvariant:
    def _bin_weigh_setup(self, api):
        """Confirmed order + BATCHING batch; corn bin replenished with 20t."""
        ctx = setup_batching_batch(tons=10, credit_limit_cents=1000000)
        return ctx

    def test_weighment_drawdown_reduces_bin_on_hand(self, api):
        """PRD §3.3: "The running level obeys a conservation law: `on_hand_tons` is always `cumulative_replenished_tons` minus the sum of `actual_tons` over the bin's `RECORDED` weighments."
        PRD §3.6: "Recording is never free of side effects: the bin's `on_hand_tons` drops by `actual_tons` (a draw to exactly zero flips the bin `READY` → `EMPTY`)"

        Design: Difficulty/compensating_invariant/bin_inventory_weigh_then_void_restores_on_hand
        """
        ctx = self._bin_weigh_setup(api)
        before = validate_success(api.get_bin(ctx["bin_corn"]["id"], MM), 200)
        assert before["on_hand_tons"] == pytest.approx(20, abs=1e-6)
        assert before["cumulative_replenished_tons"] == pytest.approx(20, abs=1e-6)

        w = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                             ctx["bin_corn"]["id"], 4.000, ctx["op"]["id"])
        mid = validate_success(api.get_bin(ctx["bin_corn"]["id"], MM), 200)
        assert mid["on_hand_tons"] == pytest.approx(16, abs=1e-6), "20 - 4.000"
        assert mid["cumulative_replenished_tons"] == pytest.approx(20, abs=1e-6), (
            "cumulative replenished never moves on a drawdown")

    def test_void_restores_bin_on_hand_and_marks_void(self, api):
        """PRD §3.3: "Replenish X, weigh Y, then void that same weighment, and the bin reads X again."
        PRD §3.6: "Voiding is the compensating action: it adds `actual_tons` back onto the bin's `on_hand_tons` (a bin sitting at zero returns `EMPTY` → `READY`)"

        Design: Difficulty/compensating_invariant/bin_inventory_weigh_then_void_restores_on_hand
        """
        ctx = self._bin_weigh_setup(api)
        w = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                             ctx["bin_corn"]["id"], 4.000, ctx["op"]["id"])

        voided = validate_success(
            api.void_weighment(w["id"], make_operator_headers(ctx["op"]["id"])), 200)
        assert voided["status"] == "VOID"

        after = validate_success(api.get_bin(ctx["bin_corn"]["id"], MM), 200)
        assert_bin(after)
        assert after["on_hand_tons"] == pytest.approx(20, abs=1e-6), (
            "weigh + void conserves physical tons")
        assert after["cumulative_replenished_tons"] == pytest.approx(20, abs=1e-6)
        assert after["status"] == "READY"


class TestContractTonnageInvariant:
    def _contract_weigh_setup(self, api):
        """Corn contract 50t @ 29000 covering the clock; confirmed order;
        BATCHING batch; corn bin 20t."""
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        add_price_tick(corn["id"], 30000)
        add_price_tick(sbm["id"], 52000)
        contract = make_contract(corn["id"], supplier_ref="SUP-1",
                                 fixed_price_cents_per_ton=29000, total_tons=50,
                                 window_start_date="2026-04-01",
                                 window_end_date="2026-06-30")
        formula = make_active_formula("F-GROW")
        customer = make_customer("Acme Farms", 1000000)
        order = make_order(customer, formula["id"], 10)
        order = confirm_order(order, customer["id"])
        op = make_employee("Olly Operator", "OPERATOR")
        line = make_line("L1")
        bin_corn = make_stocked_bin("BIN-C", corn["id"], 20)
        batch = make_batch(order["id"], line["id"], 10)
        start_batch(batch["id"], op["id"])
        return {"corn": corn, "contract": contract, "op": op,
                "batch": batch, "bin_corn": bin_corn}

    def test_contract_weighment_consumes_remaining(self, api):
        """PRD §3.2: "A contract's `consumed_tons` is the sum of `actual_tons` over its `RECORDED` weighments, and its `remaining_tons` is `total_tons` minus `consumed_tons`, both carried to three decimals."
        PRD §3.6: "a contract-sourced weighment raises the contract's `consumed_tons` — a remainder of exactly zero flips the contract `OPEN` → `EXHAUSTED` and fires the §3.2 cascade."

        Design: Difficulty/compensating_invariant/contract_tonnage_weigh_then_void_restores_remaining
        """
        ctx = self._contract_weigh_setup(api)
        w = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                             ctx["bin_corn"]["id"], 4.000, ctx["op"]["id"])
        assert_weighment(w)
        assert w["source"] == "CONTRACT"
        assert w["unit_price_cents"] == 29000

        contract = validate_success(api.get_contract(ctx["contract"]["id"], MM), 200)
        assert contract["consumed_tons"] == pytest.approx(4.000, abs=1e-6)
        assert contract["remaining_tons"] == pytest.approx(46.000, abs=1e-6)
        assert contract["status"] == "OPEN", "remaining 46 > 0: no EXHAUSTED flip"

    def test_contract_void_restores_remaining_and_stays_open(self, api):
        """PRD §3.2: "The conservation invariant holds: weighing W tons against a contract and then voiding that same weighment restores `remaining_tons` to its prior value."
        PRD §3.6: "it subtracts `actual_tons` from the contract's `consumed_tons` when `contract_id` is set (a contract whose remainder climbs back above zero moves `EXHAUSTED` → `OPEN`, firing the recompute cascade)"

        Design: Difficulty/compensating_invariant/contract_tonnage_weigh_then_void_restores_remaining
        """
        ctx = self._contract_weigh_setup(api)
        w = record_weighment(ctx["batch"]["id"], ctx["corn"]["id"],
                             ctx["bin_corn"]["id"], 4.000, ctx["op"]["id"])

        validate_success(
            api.void_weighment(w["id"], make_operator_headers(ctx["op"]["id"])), 200)

        contract = validate_success(api.get_contract(ctx["contract"]["id"], MM), 200)
        assert_contract(contract)
        assert contract["consumed_tons"] == pytest.approx(0.0, abs=1e-6)
        assert contract["remaining_tons"] == pytest.approx(50, abs=1e-6), (
            "invariant: weigh + void restores remaining_tons to its prior value")
        assert contract["status"] == "OPEN"
