"""Run planning and confirmation: changeover fees, kettle-line buffers,
rounding discipline, packaging availability, credit gating, and stock
adjustment (PRD §3.4, §3.5, §2.5, §2.7)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_packaging_component,
    cancel_run,
    confirm_run,
    create_customer,
    create_formula,
    create_kettle_line,
    create_packaging_component,
    create_packaging_component_payload,
    create_production_run_payload,
    create_run,
    get_customer,
    get_formula,
    get_packaging_component,
    get_run,
    make_customer_headers,
    setup_approved_acid_formula,
    setup_approved_acidified_formula,
    setup_confirmed_run,
    setup_nut_and_none_formulas,
    setup_trial_passed_formula,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
PA = TEST_USERS["process_authority_headers"]


class TestChangeoverFee:
    """Allergen-conditional changeover fee with the predecessor selector."""

    def test_changeover_fee_standard_when_no_predecessor(self):
        """PRD §3.5: "When a predecessor exists and its formula's `allergen_class` differs from the confirming run's, the allergen changeover fee of 75000 cents applies; when the allergen classes match, or no predecessor exists at all, the standard fee of 15000 cents applies. Once locked, the fee is never recomputed — not even by later completions."
        PRD §3.5: "The predecessor is the most recent prior occupant of the same line: among occupiers whose `scheduled_end` falls at or before the confirming run's `scheduled_start`, the one with the latest `scheduled_end` wins, ties broken by the latest `created_at`."

        Design: Difficulty/combinatorial_formula/changeover_fee_allergen_conditional
        """
        ctx = setup_nut_and_none_formulas()
        run_n = create_run(
            ctx["f_nut"]["id"],
            ctx["kettle"]["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T06:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
            packaging_requirements=[],
        )
        confirm_run(run_n["id"])
        run_n_after = get_run(run_n["id"])
        assert run_n_after["changeover_fee_cents"] == 15000, (
            f"first run on a line has no predecessor; expected the standard "
            f"15000 fee, got {run_n_after['changeover_fee_cents']}"
        )

    def test_changeover_fee_allergen_switch_after_nut_run(self):
        """PRD §3.5: "When a predecessor exists and its formula's `allergen_class` differs from the confirming run's, the allergen changeover fee of 75000 cents applies; when the allergen classes match, or no predecessor exists at all, the standard fee of 15000 cents applies. Once locked, the fee is never recomputed — not even by later completions."
        PRD §3.5: "When the occupier's window ends at or before the confirming run's `scheduled_start`, a conflict exists exactly when the gap between the occupier's `scheduled_end` and the confirming run's `scheduled_start` is smaller than the required gap — a gap of exactly the required size is acceptable."

        Design: Difficulty/combinatorial_formula/changeover_fee_allergen_conditional
        """
        ctx = setup_nut_and_none_formulas()
        bottle = create_packaging_component()
        run_n = create_run(
            ctx["f_nut"]["id"],
            ctx["kettle"]["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T06:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
            packaging_requirements=[],
        )
        confirm_run(run_n["id"])

        run_a = create_run(
            ctx["f_none"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            scheduled_start="2026-09-10T14:00:00Z",
            scheduled_end="2026-09-10T18:00:00Z",
            packaging_requirements=[
                {"component_id": bottle["id"], "quantity_per_unit": 1}
            ],
        )
        confirm_run(run_a["id"])
        run_a_after = get_run(run_a["id"])
        assert run_a_after["status"] == "CONFIRMED", (
            f"a gap of exactly 4h satisfies the allergen buffer, got "
            f"{run_a_after['status']}"
        )
        assert run_a_after["changeover_fee_cents"] == 75000, (
            f"NUT -> NONE allergen switch must lock the 75000 fee, got "
            f"{run_a_after['changeover_fee_cents']}"
        )
        # 2000*120 + 75000 + round(0.8*2000*300) + 2000*50
        assert run_a_after["estimated_charge_cents"] == 895000


class TestEstimateRounding:

    def _setup_rounding_run(self):
        """ACID formula (rate 0, min_run 10) with two COPACKER_SUPPLIED lines
        at 0.05/unit @5 cents each; run planned 10, no packaging."""
        customer = create_customer()
        cell = api_client.create_pilot_cell(
            {"cell_name": "Pilot-1", "max_batch_units": 5000}, OPS
        )
        cell_data = validate_success(cell, 201)
        formula = setup_approved_acid_formula(
            customer["id"],
            cell_data["id"],
            product_name="Rounding Sauce",
            sku_code="RS-001",
            allergen_class="NONE",
            min_run_units=10,
            unit_rate_cents=0,
            batch_size_units=10,
            yield_units=10,
            trial_start="2026-09-01T08:00:00Z",
            trial_end="2026-09-01T09:00:00Z",
            supplies=[
                {
                    "ingredient_name": "Spice A",
                    "sourcing_mode": "COPACKER_SUPPLIED",
                    "quantity_per_unit": 0.05,
                    "unit_cost_cents": 5,
                },
                {
                    "ingredient_name": "Spice B",
                    "sourcing_mode": "COPACKER_SUPPLIED",
                    "quantity_per_unit": 0.05,
                    "unit_cost_cents": 5,
                },
            ],
        )
        kettle = create_kettle_line()
        run = create_run(
            formula["id"],
            kettle["id"],
            planned_units=10,
            scheduled_start="2026-09-10T08:00:00Z",
            scheduled_end="2026-09-10T09:00:00Z",
            packaging_requirements=[],
        )
        return customer, run

    def test_estimate_rounds_each_ingredient_line_before_summing(self):
        """PRD §2.6: "Charge arithmetic observes a strict rounding discipline: each extended line (an ingredient line or a packaging line) is rounded half-up to whole cents before any summation takes place, and the totals are sums of those rounded lines. The system never sums unrounded line values and rounds once at the end."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_order
        """
        _customer, run = self._setup_rounding_run()
        confirm_run(run["id"])
        run_after = get_run(run["id"])
        # base 0 + fee 15000 + round_half_up(2.5)=3 + round_half_up(2.5)=3
        assert run_after["estimated_charge_cents"] == 15006, (
            f"per-line round-then-sum must yield 15006 (sum-then-round would "
            f"yield 15005), got {run_after['estimated_charge_cents']}"
        )

    def test_per_line_rounding_total_billed_to_customer(self):
        """PRD §2.6: "Charge arithmetic observes a strict rounding discipline: each extended line (an ingredient line or a packaging line) is rounded half-up to whole cents before any summation takes place, and the totals are sums of those rounded lines. The system never sums unrounded line values and rounds once at the end."
        PRD §3.1: "That figure is the account's live billing exposure: it rises by a run's estimate at confirmation, moves by the difference between the final charge and whatever was previously applied at each completion, falls by the estimate when a confirmed run is cancelled, and falls by the final charge when a produced batch is destroyed."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_order
        """
        customer, run = self._setup_rounding_run()
        confirm_run(run["id"])
        customer_after = get_customer(customer["id"])
        assert customer_after["outstanding_billed_cents"] == 15006, (
            f"the rounded estimate must be billed as-is, got "
            f"{customer_after['outstanding_billed_cents']}"
        )


class TestKettleLineBuffer:
    """Allergen-conditional buffered-interval booking on the kettle line."""

    def test_kettle_conflict_when_gap_below_allergen_buffer(self):
        """PRD §3.5: "Between the confirming run and each occupier, a required gap applies: four hours when the two runs' formulas have different `allergen_class` values, otherwise one hour."
        PRD §3.5: "When the occupier's window ends at or before the confirming run's `scheduled_start`, a conflict exists exactly when the gap between the occupier's `scheduled_end` and the confirming run's `scheduled_start` is smaller than the required gap — a gap of exactly the required size is acceptable."
        PRD §3.5: "Any conflict rejects the confirmation with `ERR_KETTLE_LINE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/kettle_allergen_changeover_buffer
        """
        ctx = setup_nut_and_none_formulas()
        run_n = create_run(
            ctx["f_nut"]["id"],
            ctx["kettle"]["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T06:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
            packaging_requirements=[],
        )
        confirm_run(run_n["id"])
        run_a = create_run(
            ctx["f_none"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            scheduled_start="2026-09-10T12:00:00Z",
            scheduled_end="2026-09-10T16:00:00Z",
            packaging_requirements=[],
        )
        resp = api_client.confirm_production_run(run_a["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_KETTLE_LINE_CONFLICT)
        run_a_after = get_run(run_a["id"])
        assert run_a_after["status"] == "PLANNED", (
            f"a rejected confirm must leave the run PLANNED, got "
            f"{run_a_after['status']}"
        )

    def test_kettle_confirm_allowed_at_exact_buffer_boundary(self):
        """PRD §3.5: "Between the confirming run and each occupier, a required gap applies: four hours when the two runs' formulas have different `allergen_class` values, otherwise one hour."
        PRD §3.5: "When the occupier's window ends at or before the confirming run's `scheduled_start`, a conflict exists exactly when the gap between the occupier's `scheduled_end` and the confirming run's `scheduled_start` is smaller than the required gap — a gap of exactly the required size is acceptable."

        Design: Difficulty/resource_temporal_overlap/kettle_allergen_changeover_buffer
        """
        ctx = setup_nut_and_none_formulas()
        run_n = create_run(
            ctx["f_nut"]["id"],
            ctx["kettle"]["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T06:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
            packaging_requirements=[],
        )
        confirm_run(run_n["id"])
        run_a2 = create_run(
            ctx["f_none"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            scheduled_start="2026-09-10T14:00:00Z",
            scheduled_end="2026-09-10T18:00:00Z",
            packaging_requirements=[],
        )
        confirmed = confirm_run(run_a2["id"])
        assert confirmed["status"] == "CONFIRMED", (
            f"a gap of exactly the required 4h must be acceptable, got "
            f"{confirmed['status']}"
        )


class TestPackagingAvailabilityBoundary:

    def _setup_exact_availability_run(self):
        """ACID formula (min 500, rate 200, salt 0.1 @50) auto-approved; a
        bottle with exactly 2000 on hand; run planned 2000 at 1 bottle/unit."""
        customer = create_customer()
        cell_resp = api_client.create_pilot_cell(
            {"cell_name": "Pilot-1", "max_batch_units": 5000}, OPS
        )
        cell = validate_success(cell_resp, 201)
        formula = setup_approved_acid_formula(
            customer["id"],
            cell["id"],
            product_name="Budget BBQ",
            sku_code="BB-001",
            allergen_class="NONE",
            min_run_units=500,
            unit_rate_cents=200,
            supplies=[
                {
                    "ingredient_name": "Sea salt",
                    "sourcing_mode": "COPACKER_SUPPLIED",
                    "quantity_per_unit": 0.1,
                    "unit_cost_cents": 50,
                }
            ],
        )
        kettle = create_kettle_line()
        bottle = create_packaging_component(
            component_name="5oz bottle",
            component_type="BOTTLE",
            unit_cost_cents=10,
            initial_on_hand_units=2000,
        )
        run = create_run(
            formula["id"],
            kettle["id"],
            planned_units=2000,
            scheduled_start="2026-09-15T08:00:00Z",
            scheduled_end="2026-09-15T12:00:00Z",
            packaging_requirements=[
                {"component_id": bottle["id"], "quantity_per_unit": 1}
            ],
        )
        return customer, run, bottle

    def test_confirm_succeeds_when_requirement_equals_availability(self):
        """PRD §3.5: "For each line of `packaging_requirements`, the requirement is the line's `quantity_per_unit` multiplied by `planned_units`, and the component's availability is its `on_hand_units` minus its `reserved_units`; a shortage exists only when the requirement strictly exceeds availability, so a requirement exactly equal to availability passes."

        Design: Difficulty/boundary_precision_check/packaging_exact_availability_allows_confirm
        """
        _customer, run, bottle = self._setup_exact_availability_run()
        confirmed = confirm_run(run["id"])
        assert confirmed["status"] == "CONFIRMED", (
            f"required 2000 == available 2000 must pass, got "
            f"{confirmed['status']}"
        )
        bottle_after = get_packaging_component(bottle["id"])
        assert bottle_after["reserved_units"] == 2000
        assert bottle_after.get("available_units") == 0

    def test_estimate_at_exact_availability_boundary(self):
        """PRD §3.5: "The units billed are the greater of `planned_units` and the formula's `min_run_units` — the contractual minimum run size is billed even when the plan is smaller."
        PRD §3.5: "The `estimated_charge_cents` is the base plus the locked changeover fee plus the ingredient total plus the packaging total."

        Design: Difficulty/boundary_precision_check/packaging_exact_availability_allows_confirm
        """
        _customer, run, _bottle = self._setup_exact_availability_run()
        confirm_run(run["id"])
        run_after = get_run(run["id"])
        # 2000*200 + 15000 + round(0.1*2000*50) + 2000*10
        assert run_after["estimated_charge_cents"] == 445000


class TestCreditGate:

    def _setup_over_credit_run(self):
        """Customer with credit_limit 1000; ACID formula (min 500, rate 200,
        salt 0.1 @50); run planned 1000 whose estimate would be 220000."""
        customer = create_customer(
            brand_name="Tiny Brand",
            contact_email="t@x.example",
            credit_limit_cents=1000,
        )
        cell_resp = api_client.create_pilot_cell(
            {"cell_name": "Pilot-1", "max_batch_units": 5000}, OPS
        )
        cell = validate_success(cell_resp, 201)
        formula = setup_approved_acid_formula(
            customer["id"],
            cell["id"],
            product_name="Budget BBQ",
            sku_code="BB-001",
            allergen_class="NONE",
            min_run_units=500,
            unit_rate_cents=200,
            supplies=[
                {
                    "ingredient_name": "Sea salt",
                    "sourcing_mode": "COPACKER_SUPPLIED",
                    "quantity_per_unit": 0.1,
                    "unit_cost_cents": 50,
                }
            ],
        )
        kettle = create_kettle_line()
        run = create_run(
            formula["id"],
            kettle["id"],
            planned_units=1000,
            scheduled_start="2026-09-20T08:00:00Z",
            scheduled_end="2026-09-20T12:00:00Z",
            packaging_requirements=[],
        )
        return run

    def test_confirm_rejected_when_credit_exceeded(self):
        """PRD §3.5: "Only now does the credit gate apply: the customer's `outstanding_billed_cents` plus this `estimated_charge_cents` must not exceed `credit_limit_cents`. The breach test is strict — a sum exactly equal to the limit is permitted, and only a sum exceeding it is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal
        """
        run = self._setup_over_credit_run()
        resp = api_client.confirm_production_run(run["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)

    def test_confirm_state_gate_fires_before_credit_check(self):
        """PRD §2.7: "Every request travels through the same ordered validation pipeline, and a failure at any stage masks every later stage — the caller always receives the earliest applicable error."
        PRD §2.7: "The credit check is always the final gate of run confirmation, so a financing breach never masks, and is never masked by, an operational conflict: `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."
        PRD §3.5: "The run must be in `PLANNED` (`ERR_RUN_NOT_PLANNED`) and its formula must be `APPROVED` (`ERR_FORMULA_NOT_APPROVED`)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_fiscal
        """
        run = self._setup_over_credit_run()
        first = api_client.confirm_production_run(run["id"], OPS)
        validate_error(first, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        cancel_run(run["id"])

        second = api_client.confirm_production_run(run["id"], OPS)
        validate_error(second, ApiErrorId.ERR_RUN_NOT_PLANNED)
        run_after = get_run(run["id"])
        assert run_after["status"] == "CANCELLED"


class TestConfirmFormulaGate:

    def test_confirm_rejected_until_formula_approved(self):
        """PRD §3.5: "The run must be in `PLANNED` (`ERR_RUN_NOT_PLANNED`) and its formula must be `APPROVED` (`ERR_FORMULA_NOT_APPROVED`)."
        PRD §3.4: "The formula must be in `TRIAL_PASSED` or `APPROVED` — attempting to plan a run against a formula still in `DRAFT` or `IN_TRIAL` is rejected with `ERR_FORMULA_NOT_APPROVED` — and `planned_units` beyond the line's `capacity_units` is refused with `ERR_BATCH_EXCEEDS_CAPACITY`."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_formula_approved
        """
        ctx = setup_trial_passed_formula()
        kettle = create_kettle_line()
        run = create_run(
            ctx["formula"]["id"],
            kettle["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T08:00:00Z",
            scheduled_end="2026-09-10T12:00:00Z",
            packaging_requirements=[],
        )
        resp = api_client.confirm_production_run(run["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_APPROVED)
        run_after = get_run(run["id"])
        assert run_after["status"] == "PLANNED"

    def test_confirm_succeeds_once_letter_activated(self):
        """PRD §3.5: "The run must be in `PLANNED` (`ERR_RUN_NOT_PLANNED`) and its formula must be `APPROVED` (`ERR_FORMULA_NOT_APPROVED`)."
        PRD §3.3: "Activation carries two side effects: every other `ACTIVE` letter for the same formula is moved to `SUPERSEDED`, so at most one letter per formula is ever `ACTIVE`, and a formula sitting in `TRIAL_PASSED` advances to `APPROVED` (a formula already `APPROVED` simply stays there)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_formula_approved
        """
        ctx = setup_trial_passed_formula()
        kettle = create_kettle_line()
        run = create_run(
            ctx["formula"]["id"],
            kettle["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T08:00:00Z",
            scheduled_end="2026-09-10T12:00:00Z",
            packaging_requirements=[],
        )
        resp = api_client.confirm_production_run(run["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_APPROVED)

        activate = api_client.activate_process_authority_letter(
            ctx["letter"]["id"], PA
        )
        validate_success(activate, 200)
        confirmed = confirm_run(run["id"])
        assert confirmed["status"] == "CONFIRMED", (
            f"once the letter activates the formula, confirm must succeed, "
            f"got {confirmed['status']}"
        )


class TestChangeoverPredecessorFiltering:

    def test_cancelled_run_excluded_from_changeover_predecessor(self):
        """PRD §3.5: "A kettle line is considered occupied by its runs in `CONFIRMED`, `COMPLETED`, `ON_HOLD`, `REWORK`, and `RELEASED`; runs in `PLANNED`, `CANCELLED`, or `DESTROYED` do not occupy the line."
        PRD §3.5: "When a predecessor exists and its formula's `allergen_class` differs from the confirming run's, the allergen changeover fee of 75000 cents applies; when the allergen classes match, or no predecessor exists at all, the standard fee of 15000 cents applies. Once locked, the fee is never recomputed — not even by later completions."

        Design: Corner/calculations/changeover_predecessor_excludes_cancelled_runs
        """
        ctx = setup_nut_and_none_formulas()
        bottle = create_packaging_component()
        run_n = create_run(
            ctx["f_nut"]["id"],
            ctx["kettle"]["id"],
            planned_units=1000,
            scheduled_start="2026-09-10T06:00:00Z",
            scheduled_end="2026-09-10T10:00:00Z",
            packaging_requirements=[],
        )
        confirm_run(run_n["id"])
        cancel_run(run_n["id"])

        run_a = create_run(
            ctx["f_none"]["id"],
            ctx["kettle"]["id"],
            planned_units=2000,
            scheduled_start="2026-09-10T14:00:00Z",
            scheduled_end="2026-09-10T18:00:00Z",
            packaging_requirements=[
                {"component_id": bottle["id"], "quantity_per_unit": 1}
            ],
        )
        confirm_run(run_a["id"])
        run_a_after = get_run(run_a["id"])
        assert run_a_after["changeover_fee_cents"] == 15000, (
            f"CANCELLED runs are not occupiers, so no predecessor; expected "
            f"15000, got {run_a_after['changeover_fee_cents']}"
        )
        # 2000*120 + 15000 + round(0.8*2000*300) + 2000*50
        assert run_a_after["estimated_charge_cents"] == 835000


class TestRunReads:

    def test_run_read_back_shows_computed_charges(self):
        """PRD §3.4: "Creation pins the formula's current `revision` into the run's `formula_revision`, so the run forever records which recipe revision it was planned against, and the run begins in `PLANNED` status. Until confirmation, `changeover_fee_cents` and `estimated_charge_cents` carry no value; until completion, `actual_units_produced`, `measured_ph`, `measured_water_activity`, and `final_charge_cents` remain unset."
        PRD §3.5: "A successful confirmation moves the run to `CONFIRMED`, bumps its `version`, and posts three sets of effects: the customer's `outstanding_billed_cents` increases by `estimated_charge_cents`; each packaging requirement reserves stock, raising the component's `reserved_units` by `quantity_per_unit` multiplied by `planned_units`; and each `CUSTOMER_SUPPLIED` line draws down consignment, reducing `consigned_units_on_hand` by the same per-line quantity."

        Design: Corner/endpoints/run_get_after_confirm_shows_computed_charges
        """
        ctx = setup_confirmed_run()
        run = get_run(ctx["run"]["id"])
        assert run["status"] == "CONFIRMED"
        assert run["estimated_charge_cents"] == 859000
        assert run["changeover_fee_cents"] == 15000
        assert run["formula_revision"] == 1
        assert run.get("final_charge_cents") is None, (
            "final_charge_cents must remain unset before any completion"
        )

    def test_run_create_with_unknown_formula_returns_404(self):
        """PRD §2.7: "Only after the path resolves are foreign keys in the request body — `formula_id`, `kettle_line_id`, `pilot_cell_id`, `production_run_id`, and each `component_id` inside `packaging_requirements` — checked against the same 404 family."

        Design: Corner/endpoints/run_create_unknown_formula_not_found
        """
        kettle = create_kettle_line()
        resp = api_client.create_production_run(
            create_production_run_payload(
                NON_EXISTENT_UUID,
                kettle["id"],
                planned_units=100,
                scheduled_start="2026-09-10T08:00:00Z",
                scheduled_end="2026-09-10T12:00:00Z",
            ),
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_FOUND)


class TestPackagingComponentStock:

    def test_component_create_ignores_client_reserved_units(self):
        """PRD §3.4: "An `OpsAdmin` creates a component with a `component_name`, a `component_type` of `BOTTLE`, `CAP`, `LABEL`, or `CASE`, a `unit_cost_cents` of zero or more, and an `initial_on_hand_units` that seeds physical stock. At creation `on_hand_units` equals `initial_on_hand_units` and `reserved_units` is zero; the derived `available_units` is always `on_hand_units` minus `reserved_units`."

        Design: Corner/entities/component_create_computed_input_ignored
        """
        resp = api_client.create_packaging_component(
            create_packaging_component_payload(reserved_units=999), OPS
        )
        data = validate_success(resp, expected_status=201)
        assert_packaging_component(data)
        assert data["reserved_units"] == 0, (
            f"client-supplied reserved_units must be ignored, got "
            f"{data['reserved_units']}"
        )
        assert data["on_hand_units"] == 100_000
        if data.get("available_units") is not None:
            assert data["available_units"] == 100_000

    def test_component_stock_adjustment_below_reserved_rejected(self):
        """PRD §3.4: "One invariant holds at all times: `on_hand_units` never drops below `reserved_units`. When an `OpsAdmin` adjusts stock by setting a new `on_hand_units`, a value below the current `reserved_units` is rejected with `ERR_STOCK_BELOW_RESERVED`, and the write is guarded by `expected_component_version` per §2.5, incrementing the component's `version` on success."

        Design: Corner/validations/component_stock_below_reserved_rejected
        """
        ctx = setup_confirmed_run(packaging="bottle")
        bottle = get_packaging_component(ctx["bottle"]["id"])
        assert bottle["reserved_units"] == 2000

        resp = api_client.update_packaging_component(
            ctx["bottle"]["id"],
            {
                "on_hand_units": 1000,
                "expected_component_version": bottle["version"],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_STOCK_BELOW_RESERVED)
        bottle_after = get_packaging_component(ctx["bottle"]["id"])
        assert bottle_after["on_hand_units"] == 100_000

    def test_component_adjustment_rejects_stale_expected_version(self):
        """PRD §2.5: "Adjusting a packaging component's stock requires the non-optional input field `expected_component_version`, carrying the client's last observed `version` of that `PackagingComponent`. The same mismatch handling applies: rejection with `ERR_STALE_VERSION` (HTTP 412) instead of clobbering stock changes the client never saw."

        Design: Corner/cross_cutting_layers/component_put_stale_version_rejected
        """
        component = create_packaging_component()
        observed_version = component["version"]

        first = api_client.update_packaging_component(
            component["id"],
            {"on_hand_units": 95000, "expected_component_version": observed_version},
            OPS,
        )
        updated = validate_success(first, 200)
        assert updated["on_hand_units"] == 95000
        assert updated["version"] == observed_version + 1

        replay = api_client.update_packaging_component(
            component["id"],
            {"on_hand_units": 90000, "expected_component_version": observed_version},
            OPS,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        current = get_packaging_component(component["id"])
        assert current["on_hand_units"] == 95000
        assert current["version"] == observed_version + 1


class TestProductionResourceRbac:

    def test_customer_cannot_create_kettle_line(self):
        """PRD §2.1: "Access to every endpoint is further restricted by role; an attempt to perform an action outside the caller's designated role set is rejected with an `ERR_FORBIDDEN` error."
        PRD §4: "| POST | `/copack/kettle-lines` | Create a kettle/fill line | OpsAdmin |"

        Design: Corner/rbac/customer_cannot_create_kettle_line
        """
        customer = create_customer()
        resp = api_client.create_kettle_line(
            {"line_name": "Kettle-9", "capacity_units": 1000},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
