"""Quotation, fulfillable projections, minimum-run, credit, OCC, and unit/money
conservation invariants on production orders."""
from test_helpers import (
    ApiErrorId,
    approve_label_artwork,
    approve_review,
    activate_formula,
    assert_formula,
    assert_order,
    allocate_lots,
    allocation_item,
    cancel_order,
    claim_review,
    complete_run,
    confirm_order,
    create_active_formula,
    create_batch,
    create_component,
    create_customer,
    create_customer_supplied_component,
    create_formula,
    create_line,
    create_lot,
    create_order,
    create_revision,
    declare_shortfall,
    escalate_shortfall,
    in_progress_run_ctx,
    make_customer_rep_headers,
    open_review,
    patch_order_units,
    record_ipc_check,
    release_batch,
    schedule_run,
    start_mixing,
    start_run,
    submit_formula,
    validate_error,
    validate_success,
    waive_variant,
)
from test_helpers.fixtures import QA1, QA2


class TestFormulaCostVariants:
    def test_formula_cost_standard_vs_current_lot(self, api, formulation_chemist_headers):
        """PRD §3.2: "The standard variant, `cost_estimate_standard_per_kg_cents`,
        prices every ingredient at its component's `standard_cost_per_kg_cents`.
        The current-lot variant, `cost_estimate_current_lot_per_kg_cents`, prices
        each ingredient at the quantity-weighted average of
        `unit_cost_per_kg_cents` across that component's lots currently standing
        `AVAILABLE`, weighted by each lot's `quantity_available`".
        PRD §3.2: "a lot receipt additionally refreshes the current-lot variant."

        Design: Difficulty/dual_variant_calc/formula_cost_standard_vs_current_lot
        """
        customer = create_customer()
        comp_a = create_component(name="Water", standard_cost_per_kg_cents=1000)
        comp_b = create_component(name="Glycerin", standard_cost_per_kg_cents=2000)
        comp_c = create_component(name="Parfum", kind="BULK_FRAGRANCE",
                                  standard_cost_per_kg_cents=10000)
        formula = create_formula(
            customer["id"],
            ingredients=[
                {"inci_name": "AQUA", "component_id": comp_a["id"], "percentage": 70},
                {"inci_name": "GLYCERIN", "component_id": comp_b["id"], "percentage": 25},
                {"inci_name": "PARFUM", "component_id": comp_c["id"], "percentage": 5},
            ],
        )
        # Priced AVAILABLE lots of B only: weighted avg = (10*1800 + 30*2200)/40 = 2100.
        create_lot(comp_b["id"], lot_code="B1", quantity_received=10, unit_cost_per_kg_cents=1800)
        create_lot(comp_b["id"], lot_code="B2", quantity_received=30, unit_cost_per_kg_cents=2200)

        fetched = validate_success(api.get_formula(formula["id"], formulation_chemist_headers), 200)
        assert_formula(fetched)
        # standard: 0.70*1000 + 0.25*2000 + 0.05*10000 = 1700
        assert fetched["cost_estimate_standard_per_kg_cents"] == 1700
        # current-lot: 0.70*1000 + 0.25*2100 + 0.05*10000 = 1725
        assert fetched["cost_estimate_current_lot_per_kg_cents"] == 1725
        assert fetched["cost_estimate_current_lot_per_kg_cents"] != fetched["cost_estimate_standard_per_kg_cents"]

    def test_formula_cost_fallback_to_standard_when_no_priced_lots(self, api, formulation_chemist_headers):
        """PRD §3.2: "lots without a recorded `unit_cost_per_kg_cents` are
        excluded from both the weighted sum and its divisor, and when a component
        has no priced available lots at all the estimate falls back to that
        component's standard cost."

        Design: Difficulty/dual_variant_calc/formula_cost_standard_vs_current_lot
        """
        customer = create_customer()
        comp_a = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_formula(customer["id"], component_id=comp_a["id"])
        # Unpriced lot receipt refreshes the current-lot variant but cannot
        # contribute to the weighted average.
        create_lot(comp_a["id"], lot_code="A1", quantity_received=50)

        fetched = validate_success(api.get_formula(formula["id"], formulation_chemist_headers), 200)
        assert fetched["cost_estimate_standard_per_kg_cents"] == 1000
        assert fetched["cost_estimate_current_lot_per_kg_cents"] == 1000


class TestFulfillableVariants:
    def _setup_fulfillable_scenario(self):
        customer = create_customer(minimum_run_units=1000)
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        bottle = create_customer_supplied_component(customer["id"], name="Bottle", kind="PRIMARY_PACK")
        cap = create_customer_supplied_component(customer["id"], name="Cap", kind="SECONDARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[
                {"component_id": bottle["id"], "units_per_product": 1},
                {"component_id": cap["id"], "units_per_product": 1},
            ],
        )
        lots = {
            "bottle_ok": create_lot(bottle["id"], lot_code="BT1", quantity_received=800),
            "bottle_variant": create_lot(bottle["id"], lot_code="BT2", quantity_received=300,
                                         sensorial_profile="MINOR_VARIANT"),
            "cap_ok": create_lot(cap["id"], lot_code="CP1", quantity_received=1200),
        }
        return customer, formula, lots

    def test_order_fulfillable_conservative_vs_optimistic(self, api):
        """PRD §3.5: "The conservative pool for a component sums
        `quantity_available` over the eligible lots whose `sensorial_profile` is
        `WITHIN_SPEC` or whose `variant_waiver` stands `WAIVED`, and adds the
        reserved `quantity` of this order's own `RESERVED` allocations on those
        same lots".
        PRD §3.5: "The optimistic pool adds, on top of the conservative pool,
        `quantity_available` over eligible lots flagged `MINOR_VARIANT` whose
        waiver still stands `PENDING` — it assumes those waivers will be granted,
        and the two projections diverge exactly when such lots exist."

        Design: Difficulty/dual_variant_calc/order_fulfillable_conservative_vs_optimistic
        """
        customer, formula, _ = self._setup_fulfillable_scenario()
        resp = api.create_order(
            {"formula_id": formula["id"], "requested_units": 1000},
            make_customer_rep_headers(customer["id"]),
        )
        order = validate_success(resp, 201)
        assert_order(order)
        # bottle: conservative 800 (WITHIN_SPEC only) vs optimistic 800+300.
        assert order["fulfillable_units_conservative"] == 800
        assert order["fulfillable_units_optimistic"] == 1100
        assert order["fulfillable_units_optimistic"] != order["fulfillable_units_conservative"]

    def test_fulfillable_recomputed_on_waiver(self, api, production_planner_headers):
        """PRD §3.5: "Both are recomputed at order placement, on any change to
        `requested_units`, on lot receipt, on allocation release, on a waiver
        decision, and on shortfall escalation."
        PRD §3.1: "A `decision` of `WAIVED` moves `variant_waiver` from `PENDING`
        to `WAIVED` and makes the lot allocatable."

        Design: Difficulty/dual_variant_calc/order_fulfillable_conservative_vs_optimistic
        """
        customer, formula, lots = self._setup_fulfillable_scenario()
        order = create_order(customer["id"], formula["id"], 1000)
        assert order["fulfillable_units_conservative"] == 800

        waive_variant(lots["bottle_variant"]["id"], customer["id"], "WAIVED")

        fetched = validate_success(api.get_order(order["id"], production_planner_headers), 200)
        # The waived 300-unit lot joins the conservative pool: 800 + 300 = 1100.
        assert fetched["fulfillable_units_conservative"] == 1100
        assert fetched["fulfillable_units_optimistic"] == 1100


class TestQuoteRounding:
    def _setup_rounding_formula(self):
        customer = create_customer(name="Round Corp", minimum_run_units=500)
        comp_a = create_component(name="A", standard_cost_per_kg_cents=100.05)
        comp_b = create_component(name="B", standard_cost_per_kg_cents=100.05)
        comp_c = create_component(name="C", kind="COLORANT", standard_cost_per_kg_cents=200)
        formula = create_active_formula(
            customer["id"],
            ingredients=[
                {"inci_name": "A", "component_id": comp_a["id"], "percentage": 40},
                {"inci_name": "B", "component_id": comp_b["id"], "percentage": 40},
                {"inci_name": "C", "component_id": comp_c["id"], "percentage": 20},
            ],
        )
        return customer, formula

    def test_quote_per_line_rounding_then_sum(self, api):
        """PRD §3.4: "each ingredient's line cost is that mass multiplied by its
        component's `standard_cost_per_kg_cents`, rounded half-up to whole cents;
        and the subtotal sums the rounded line costs — the rounding is pinned per
        line, never deferred to a single rounding at the end."
        PRD §2.6: "summing unrounded values and rounding once at the end is a
        different, non-conforming algorithm whose results diverge by cents."

        Design: Difficulty/combinatorial_formula/quote_per_line_rounding_then_sum
        """
        customer, formula = self._setup_rounding_formula()
        resp = api.create_order(
            {"formula_id": formula["id"], "requested_units": 500},
            make_customer_rep_headers(customer["id"]),
        )
        order = validate_success(resp, 201)
        # Per-line: A 10kg*100.05=1000.5->1001; B ->1001; C 5kg*200=1000;
        # materials 3002 + fee 500*50=25000 => 28002.
        assert order["quote_total_cents"] == 28002

    def test_quote_recomputed_on_units_patch(self, api, production_planner_headers):
        """PRD §3.4: "Quotation runs at placement, again on any change to
        `requested_units`, and again at confirmation, storing its result as
        `quote_total_cents`."
        PRD §3.4: "A successful update recomputes the quote and both fulfillable
        projections and increments the order's `version` by one."

        Design: Difficulty/combinatorial_formula/quote_per_line_rounding_then_sum
        """
        customer, formula = self._setup_rounding_formula()
        order = create_order(customer["id"], formula["id"], 500)
        assert order["quote_total_cents"] == 28002

        updated = patch_order_units(order["id"], customer["id"], 501, order["version"])
        assert updated["requested_units"] == 501
        # Per-line at 501 units: A 10.02kg*100.05=1002.501->1003; B ->1003;
        # C 5.01kg*200=1002; materials 3008 + fee 501*50=25050 => 28058.
        assert updated["quote_total_cents"] == 28058


class TestFeeTierBoundary:
    def test_quote_filling_fee_tier_boundary(self, api):
        """PRD §3.4: "The filling fee applies a per-unit rate read from
        `requested_units`: 50 cents per unit when the order is for at most 5,000
        units, 40 cents when it is for at most 20,000, and 30 cents beyond
        20,000."

        Design: Corner/calculations/quote_filling_fee_tier_boundary
        """
        customer = create_customer(minimum_run_units=1000)
        component = create_component(standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=component["id"])

        order_5000 = create_order(customer["id"], formula["id"], 5000)
        # materials 250kg*1000=250000 + fee 5000*50=250000 => 500000
        assert order_5000["quote_total_cents"] == 500000

        order_5001 = create_order(customer["id"], formula["id"], 5001)
        # materials 250.05kg->250050 + fee 5001*40=200040 => 450090
        assert order_5001["quote_total_cents"] == 450090


class TestFormulaActiveGate:
    def test_order_create_requires_formula_active(self, api, formulation_chemist_headers):
        """PRD §3.4: "Two referential gates apply at placement, evaluated in this
        order: the formula must belong to the ordering customer, failing with
        `ERR_FORMULA_CUSTOMER_MISMATCH` (HTTP 422), and the formula must stand
        `ACTIVE`, failing with `ERR_FORMULA_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_formula_active
        """
        customer = create_customer()
        component = create_component()
        formula = create_formula(customer["id"], component_id=component["id"])
        submit_formula(formula["id"])
        review = open_review(formula["id"], "INCI_LIST")
        claim_review(review["id"])
        approve_review(review["id"])
        # Formula is APPROVED, not yet ACTIVE.
        resp = api.create_order(
            {"formula_id": formula["id"], "requested_units": 1000},
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_ACTIVE, 409)

        activate_formula(formula["id"])
        created = validate_success(api.create_order(
            {"formula_id": formula["id"], "requested_units": 1000},
            make_customer_rep_headers(customer["id"])), 201)
        assert_order(created)
        assert created["status"] == "DRAFT"

    def test_order_create_rejected_for_draft_formula(self, api):
        """PRD §3.4: "Two referential gates apply at placement, evaluated in this
        order: the formula must belong to the ordering customer, failing with
        `ERR_FORMULA_CUSTOMER_MISMATCH` (HTTP 422), and the formula must stand
        `ACTIVE`, failing with `ERR_FORMULA_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_create_requires_formula_active
        """
        customer = create_customer()
        component = create_component()
        formula = create_formula(customer["id"], component_id=component["id"])
        resp = api.create_order(
            {"formula_id": formula["id"], "requested_units": 1000},
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_ACTIVE, 409)


class TestConfirmPriorityAndCredit:
    QUOTE_2000_UNITS = 270000  # 70/25/5 @1000/2000/10000: 170000 materials + 100000 fee

    def _setup_credit_scenario(self):
        customer = create_customer(credit_limit_cents=300000)
        comp_a = create_component(name="Water", standard_cost_per_kg_cents=1000)
        comp_b = create_component(name="Glycerin", standard_cost_per_kg_cents=2000)
        comp_c = create_component(name="Parfum", kind="BULK_FRAGRANCE",
                                  standard_cost_per_kg_cents=10000)
        formula = create_active_formula(
            customer["id"],
            ingredients=[
                {"inci_name": "AQUA", "component_id": comp_a["id"], "percentage": 70},
                {"inci_name": "GLYCERIN", "component_id": comp_b["id"], "percentage": 25},
                {"inci_name": "PARFUM", "component_id": comp_c["id"], "percentage": 5},
            ],
        )
        return customer, formula

    def test_state_vs_fiscal_on_confirm(self, api):
        """PRD §2.8: "When a request fails several rules at once, the server
        reports the failure in a fixed evaluation order: first authentication of
        the headers (§2.1), then role authorization, then the
        segregation-of-duties actor check on batch release (§3.6), then existence
        of every identifier in the path and every referenced foreign identifier
        in the body (`formula_id`, `lot_id`, `line_id`, `batch_id`, `chamber_id`,
        `component_id`, and the like — any missing one yields `ERR_NOT_FOUND`,
        HTTP 404), then confidentiality and ownership scoping (§2.10), then
        optimistic-concurrency version matching (§2.7), then state-transition
        legality (`ERR_INVALID_STATE`, HTTP 409 — a transition attempted from a
        state that does not declare it, or from any terminal state, is rejected),
        then the domain safety, referential, and constraint rules of §3, then
        request-shape validation (`ERR_VALIDATION`, HTTP 400 — missing or invalid
        required fields, invalid enum members, or an ingredient list whose
        percentages fail to sum to 100 within one-hundredth of a point in either
        direction), and finally the fiscal rules, minimum run before credit
        (§3.4)."
        PRD §2.9: "Every stateful resource moves only along the transitions
        declared for its lifecycle in §3; terminal states reject every further
        transition."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_confirm
        """
        customer, formula = self._setup_credit_scenario()
        order1 = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order1["id"], customer["id"])  # outstanding 270000 of 300000
        order2 = create_order(customer["id"], formula["id"], 2000)
        cancel_order(order2["id"], customer["id"])  # DRAFT -> CANCELLED (terminal)

        resp = api.confirm_order(order2["id"], make_customer_rep_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_confirm_credit_limit_exceeded(self, api):
        """PRD §3.4: "the customer's `outstanding_balance_cents` plus the order's
        `quote_total_cents` must not exceed the customer's `credit_limit_cents`,
        failing with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_on_confirm
        """
        customer, formula = self._setup_credit_scenario()
        order1 = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order1["id"], customer["id"])  # outstanding 270000 of 300000
        order2 = create_order(customer["id"], formula["id"], 2000)
        assert order2["quote_total_cents"] == self.QUOTE_2000_UNITS

        resp = api.confirm_order(order2["id"], make_customer_rep_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 402)


class TestMinimumRunBoundary:
    def test_requested_units_equals_minimum_run_passes(self, api):
        """PRD §3.4: "It requires the formula to stand `ACTIVE` (else
        `ERR_FORMULA_NOT_ACTIVE`), enforces the minimum run once more —
        `requested_units` must be at least the customer's `minimum_run_units`,
        with equality allowed, failing with `ERR_BELOW_MINIMUM_RUN` (HTTP 422)
        here just as at placement and at units update".

        Design: Difficulty/boundary_precision_check/requested_units_equals_minimum_run_passes
        """
        customer = create_customer(minimum_run_units=1000)
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])

        resp = api.create_order(
            {"formula_id": formula["id"], "requested_units": 999},
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_RUN, 422)

        created = validate_success(api.create_order(
            {"formula_id": formula["id"], "requested_units": 1000},
            make_customer_rep_headers(customer["id"])), 201)
        assert_order(created)
        assert created["status"] == "DRAFT"
        assert created["requested_units"] == 1000

    def test_patch_below_minimum_run_rejected(self, api):
        """PRD §3.4: "`requested_units` must be at least the customer's
        `minimum_run_units`, with equality allowed, failing with
        `ERR_BELOW_MINIMUM_RUN` (HTTP 422) here just as at placement and at units
        update".

        Design: Difficulty/boundary_precision_check/requested_units_equals_minimum_run_passes
        """
        customer = create_customer(minimum_run_units=1000)
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        order = create_order(customer["id"], formula["id"], 1000)

        resp = api.patch_order(
            order["id"],
            {"requested_units": 999, "expected_production_order_version": order["version"]},
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_RUN, 422)


class TestOrderVersionOcc:
    def test_stale_order_version_on_patch_returns_412(self, api):
        """PRD §2.7: "Updating an order's requested units
        (`PATCH /cosmfg/production-orders/{id}`) requires the non-optional input
        `expected_production_order_version`, matched against the order's current
        `version`. If another write — for example a shortfall escalation that
        reduced the order — has advanced the version since the client last read
        the order, the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from overwriting state it has not observed."

        Design: Corner/errors/stale_order_version_on_patch_returns_412
        """
        customer = create_customer(minimum_run_units=1000)
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        order = create_order(customer["id"], formula["id"], 2000)
        observed_version = order["version"]

        updated = patch_order_units(order["id"], customer["id"], 1500, observed_version)
        assert updated["requested_units"] == 1500
        assert updated["version"] > observed_version

        resp = api.patch_order(
            order["id"],
            {"requested_units": 1200, "expected_production_order_version": observed_version},
            make_customer_rep_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


class TestVersionPinning:
    def test_version_pinning_on_confirm(self, api, production_planner_headers,
                                        formulation_chemist_headers):
        """PRD §3.4: "On confirmation the order pins `formula_version_seq` to the
        formula's current `version_seq` — later formula revisions never re-target
        a confirmed order — and the customer's outstanding balance rises by the
        quoted total."
        PRD §3.2: "The child is created in `DRAFT` with `version_seq` equal to
        the parent's `version_seq` plus one".

        Design: Corner/cross_cutting_layers/version_pinning_on_confirm
        """
        customer = create_customer()
        component = create_component()
        formula = create_active_formula(customer["id"], component_id=component["id"])
        order = create_order(customer["id"], formula["id"], 1000)

        confirmed = confirm_order(order["id"], customer["id"])
        assert confirmed["formula_version_seq"] == 1

        formula_version = validate_success(
            api.get_formula(formula["id"], formulation_chemist_headers), 200)["version"]
        child = create_revision(formula["id"], formula_version, name="F v2")
        assert child["version_seq"] == 2

        fetched = validate_success(api.get_order(order["id"], production_planner_headers), 200)
        assert fetched["formula_version_seq"] == 1, "confirmed order keeps its pinned formula version"


class TestOutstandingBalanceInvariant:
    def test_customer_outstanding_confirm_cancel_reconciles(self, api, plant_director_headers):
        """PRD §3.4: "On confirmation the order pins `formula_version_seq` to the
        formula's current `version_seq` — later formula revisions never re-target
        a confirmed order — and the customer's outstanding balance rises by the
        quoted total."
        PRD §3.5: "Cancelling releases the order's `RESERVED` allocations (each
        released lot's `quantity_reserved` falls and its `quantity_available`
        rises by the released amount), moves its `SCHEDULED` filling runs to
        `ABORTED`, voids its `OPEN` and `COMMITMENT_RECEIVED` shortfall cases to
        `CLOSED_VOID`, and — for orders that had passed confirmation — decreases
        the customer's `outstanding_balance_cents` by the order's
        `quote_total_cents`."

        Design: Difficulty/compensating_invariant/customer_outstanding_confirm_cancel_reconciles
        """
        customer = create_customer()
        comp_a = create_component(name="Water", standard_cost_per_kg_cents=1000)
        comp_b = create_component(name="Glycerin", standard_cost_per_kg_cents=2000)
        comp_c = create_component(name="Parfum", kind="BULK_FRAGRANCE",
                                  standard_cost_per_kg_cents=10000)
        formula = create_active_formula(
            customer["id"],
            ingredients=[
                {"inci_name": "AQUA", "component_id": comp_a["id"], "percentage": 70},
                {"inci_name": "GLYCERIN", "component_id": comp_b["id"], "percentage": 25},
                {"inci_name": "PARFUM", "component_id": comp_c["id"], "percentage": 5},
            ],
        )
        order = create_order(customer["id"], formula["id"], 2000)
        assert order["quote_total_cents"] == 270000

        confirm_order(order["id"], customer["id"])
        mid = validate_success(api.get_customer(customer["id"], plant_director_headers), 200)
        assert mid["outstanding_balance_cents"] == 270000

        cancel_order(order["id"], customer["id"])
        end = validate_success(api.get_customer(customer["id"], plant_director_headers), 200)
        assert end["outstanding_balance_cents"] == 0

    def test_order_completion_releases_credit(self, api, plant_director_headers):
        """PRD §3.4: "Completion decreases the customer's
        `outstanding_balance_cents` by `quote_total_cents`."
        PRD §3.4: "And when a completing run brings the order's `filled_units` to
        at least its `requested_units`, the order moves from `FILLING` to
        `COMPLETED` — provided the formula's latest `LABEL_ARTWORK`-scope review
        stands `APPROVED`".

        Design: Difficulty/compensating_invariant/customer_outstanding_confirm_cancel_reconciles
        """
        ctx = in_progress_run_ctx(requested_units=1000, planned_units=1000)
        customer = ctx["customer"]
        approve_label_artwork(ctx["formula"]["id"])

        quote = ctx["order"]["quote_total_cents"]
        mid = validate_success(api.get_customer(customer["id"], plant_director_headers), 200)
        assert mid["outstanding_balance_cents"] == quote

        complete_run(ctx["run"]["id"], 1000)
        completed = validate_success(api.get_order(ctx["order"]["id"], plant_director_headers), 200)
        assert completed["status"] == "COMPLETED"
        end = validate_success(api.get_customer(customer["id"], plant_director_headers), 200)
        assert end["outstanding_balance_cents"] == 0


class TestUnitConservationInvariant:
    def test_order_units_conservation_reduce_then_fill(self, api, production_planner_headers):
        """PRD §3.4: "Because shortfall escalation subtracts forfeited volume
        from `requested_units` directly, the sum of `requested_units` and
        `forfeited_units` is conserved across escalation and filling."
        PRD §3.4: "the derived `open_units` reports the order's `requested_units`
        minus its `filled_units`."

        Design: Difficulty/compensating_invariant/order_units_conservation_reduce_then_fill
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        cap = create_customer_supplied_component(customer["id"], name="Cap", kind="SECONDARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[{"component_id": cap["id"], "units_per_product": 1}],
        )
        approve_label_artwork(formula["id"])
        order = create_confirmed_order_ctx(customer, formula, 2000)
        cap_lot = create_lot(cap["id"], lot_code="C1", quantity_received=500)
        # Reserve only part of the lot so it stays AVAILABLE: the conservative
        # pool (available 250 + this order's RESERVED 250 on the same eligible
        # lot = 500) then does not depend on how §3.5's reserved add-back
        # interacts with the AVAILABLE-to-DEPLETED transition of §3.1.
        allocate_lots(order["id"], [allocation_item(cap_lot["id"], 250)])
        shortfall = declare_shortfall(order["id"], cap["id"], 2000)
        escalate_shortfall(shortfall["id"], "REDUCE_ORDER")

        # Fill the reduced order out completely.
        batch = create_batch(order["id"], 25)
        raw_lot = create_lot(water["id"], lot_code="A1", quantity_received=50)
        allocate_lots(order["id"], [allocation_item(raw_lot["id"], 25, batch_id=batch["id"])])
        start_mixing(batch["id"])
        record_ipc_check(batch["id"], "VISCOSITY", 4000, QA1)
        record_ipc_check(batch["id"], "PH", 5.5, QA1)
        release_batch(batch["id"], QA2)
        line = create_line()
        run = schedule_run(order["id"], line["id"], batch["id"], 500)
        start_run(run["id"])
        complete_run(run["id"], 500)

        final = validate_success(api.get_order(order["id"], production_planner_headers), 200)
        assert_order(final)
        assert final["requested_units"] == 500
        assert final["forfeited_units"] == 1500
        assert final["requested_units"] + final["forfeited_units"] == 2000, "unit conservation broken"
        assert final["filled_units"] == 500
        assert final["open_units"] == 0
        assert final["status"] == "COMPLETED"

    def test_open_units_reflects_partial_fill(self, api, production_planner_headers):
        """PRD §3.4: "the derived `open_units` reports the order's
        `requested_units` minus its `filled_units`."
        PRD §3.8: "the order's `filled_units` rise by the run's good units; and
        when the order's `filled_units` reach at least its `requested_units` and
        the formula's latest `LABEL_ARTWORK` review stands `APPROVED`, the order
        completes per §3.4, otherwise it remains `FILLING` awaiting the label
        approval."

        Design: Difficulty/compensating_invariant/order_units_conservation_reduce_then_fill
        """
        ctx = in_progress_run_ctx(requested_units=1000, planned_units=1000)
        complete_run(ctx["run"]["id"], 300)

        fetched = validate_success(api.get_order(ctx["order"]["id"], production_planner_headers), 200)
        assert_order(fetched)
        assert fetched["filled_units"] == 300
        assert fetched["open_units"] == 700
        assert fetched["status"] == "FILLING"


def create_confirmed_order_ctx(customer, formula, requested_units):
    """Local helper: place and confirm an order as the owning representative."""
    order = create_order(customer["id"], formula["id"], requested_units)
    return confirm_order(order["id"], customer["id"])
