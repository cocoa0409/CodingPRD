"""Cost, margin, and the dispatch margin floor: pinned evaluation order,
weighted in-window oil pricing, locked-price fallback, the PlantManager
override, and state-before-fiscal error ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_display_case,
    create_line,
    create_oil_movement_payload,
    create_plain_product,
    create_shipment,
    get_line_fryer_oil,
    get_success_data,
    make_line_operator_headers,
    make_quality_tech_headers,
    record_weight_check,
    schedule_run,
    set_clock,
    setup_passed_run,
    start_run,
    validate_error,
)

PM = TEST_USERS["plant_manager_headers"]
RP = TEST_USERS["route_planner_headers"]


def _setup_pinned_margin_run(api):
    """Run started with no priced movement (locks 500); one 1000-lb check; an
    in-window TOP_OFF at 700; completed with 5 rejected cases."""
    product = create_plain_product()  # revenue 4000, seasoning 4.0, std 500
    line = create_line()
    run = schedule_run(line["id"], product["id"],
                       start="2026-08-02T08:00:00Z", end="2026-08-02T12:00:00Z",
                       lbs_planned=2000, cases_planned=100)
    set_clock("2026-08-02T08:00:00Z")
    run = start_run(run["id"])
    record_weight_check(run["id"], bag_weight_g=100.2,
                        lbs_fried_since_last_check=1000, avg_fry_temp_c=180.0)
    oil = get_line_fryer_oil(line["id"])
    get_success_data(api.create_oil_movement(
        create_oil_movement_payload(
            oil["id"], oil["version"], movement_type="TOP_OFF",
            gallons=1.5, unit_price_cents_per_gal=700),
        make_line_operator_headers("op-1")))
    run = get_success_data(api.complete_run(
        run["id"],
        {"lbs_produced": 2000, "cases_produced": 100, "rejected_cases": 5,
         "seasoning_actual_pct": 4.4},
        make_line_operator_headers("op-1")))
    return product, line, run


class TestMarginPinnedEvaluationOrder:
    def test_standard_margin_uses_locked_basis(self, api):
        """PRD §3.6: "The standard variant — computed at run start and stored
        as `margin_standard_cents` — uses `cases_planned`, `lbs_planned`, the
        product's `seasoning_target_pct`, and the locked oil price."
        PRD §3.4: "or, when no priced movement has ever been recorded, to the
        product's `standard_oil_price_cents_per_gal`. Once set, the locked
        price never changes."

        Design: Difficulty/combinatorial_formula/margin_actual_pinned_evaluation_order
        """
        product, line, run = _setup_pinned_margin_run(api)
        assert run["locked_oil_price_cents_per_gal"] == 500, (
            "no priced movement existed before start: the product fallback locks"
        )
        summary = get_success_data(api.get_cost_summary(run["id"], PM))
        # 100 cases * 4000 - (ingredient 160000 + oil 1500 + seasoning 72575)
        assert summary["margin_standard_cents"] == 165925

    def test_actual_margin_uses_weighted_in_window_price(self, api):
        """PRD §3.6: "The actual variant — computed at completion and stored as
        `margin_actual_cents` — uses `accepted_cases`, `lbs_produced`, the
        run's `seasoning_actual_pct`, and the in-window weighted oil price with
        its locked fallback."
        PRD §3.6: "First, the case basis: the standard variant uses
        `cases_planned`; the actual variant uses `accepted_cases`, which is
        `cases_produced` minus `rejected_cases` — rejects are determined before
        any cost is computed."
        PRD §3.6: "The per-case margin used by the dispatch floor is
        `margin_actual_cents` divided by `accepted_cases`, rounded half-up to a
        whole cent."

        Design: Difficulty/combinatorial_formula/margin_actual_pinned_evaluation_order
        """
        product, line, run = _setup_pinned_margin_run(api)
        summary = get_success_data(api.get_cost_summary(run["id"], PM))
        assert summary["accepted_cases"] == 95
        # 95 * 4000 - (ingredient 160000 + oil 2100 at the in-window 700 +
        # seasoning 79832 at 4.4 pct)
        assert summary["margin_actual_cents"] == 138068
        assert summary["margin_actual_per_case_cents"] == 1453


class TestMarginLockedFallback:
    def test_margin_actual_falls_back_to_locked_price(self, api):
        """PRD §3.6: "The actual variant prices it at the weighted average of
        `unit_price_cents_per_gal` across the line's `TOP_OFF` movements whose
        `recorded_at` falls inside the run's execution window — from
        `started_at` through `completed_at`, inclusive at both ends — weighted
        by `gallons`; when no such movement exists, the actual variant falls
        back to the locked price."

        Design: Corner/calculations/margin_actual_falls_back_to_locked_price
        """
        ctx = setup_passed_run()  # completed at the default clock, no movements
        summary = get_success_data(api.get_cost_summary(ctx["run"]["id"], PM))
        # 10 * 4000 - (ingredient 8000 + oil 75 (= 0.15 gal at locked 500) +
        # seasoning 3629 (= 1814.4 g * 2))
        assert summary["margin_actual_cents"] == 28296
        # planned == actual quantities and no price movement: variants agree
        assert summary["margin_standard_cents"] == 28296
        assert summary["margin_actual_per_case_cents"] == 2830


class TestDispatchMarginFloor:
    def _setup_low_margin_shipment(self, api):
        """PASSED run with per-case margin 2830 under a 5000 floor; DSD plan."""
        ctx = setup_passed_run(
            product_overrides={"min_margin_cents_per_case": 5000})
        shipment = create_shipment(ctx["run"]["id"], cases=1,
                                   requested_route="DSD")
        shipment = get_success_data(api.plan_shipment(shipment["id"], RP))
        assert shipment["status"] == "DSD_PLANNED"
        return ctx, shipment

    def test_margin_floor_blocks_planner_but_manager_overrides(self, api):
        """PRD §3.7: "the margin floor must hold — the per-case actual margin
        (§3.6) must be at least the product's `min_margin_cents_per_case`, else
        `ERR_MARGIN_BELOW_FLOOR`."
        PRD §3.7: "The margin floor admits one override: a caller whose role is
        `PlantManager` may set `override_margin_floor` to true in the dispatch
        payload to waive the floor; a `RoutePlanner` has no such privilege."

        Design: Corner/validations/margin_floor_blocks_planner_but_manager_overrides
        """
        _ctx, shipment = self._setup_low_margin_shipment(api)
        # per-case margin 2830 < floor 5000
        resp = api.dispatch_shipment(shipment["id"], RP)
        validate_error(resp, ApiErrorId.ERR_MARGIN_BELOW_FLOOR, 422)
        # a PlantManager without the flag is bound by the same floor
        resp = api.dispatch_shipment(shipment["id"], PM)
        validate_error(resp, ApiErrorId.ERR_MARGIN_BELOW_FLOOR, 422)
        dispatched = get_success_data(api.dispatch_shipment(
            shipment["id"], PM, {"override_margin_floor": True}))
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_at"] is not None


class TestStateBeatsFiscalOnDispatch:
    def _setup_draft_low_margin_shipment(self, api):
        """Planned-then-replanned (DRAFT) shipment on a low-margin run."""
        ctx = setup_passed_run(
            product_overrides={"min_margin_cents_per_case": 5000})
        shipment = create_shipment(ctx["run"]["id"], cases=1,
                                   requested_route="WAREHOUSE", transit_days=1)
        get_success_data(api.plan_shipment(shipment["id"], RP))
        shipment = get_success_data(api.replan_shipment(shipment["id"], RP))
        assert shipment["status"] == "DRAFT"
        return ctx, shipment

    def test_dispatch_from_draft_reports_state_not_fiscal(self, api):
        """PRD §2.9: "the target entity occupies a from-state of the invoked
        transition" is tier "6. State legality", listed before "10. Fiscal
        rules last: the co-man budget ceiling and the dispatch margin floor —
        `ERR_BUDGET_EXCEEDED` and `ERR_MARGIN_BELOW_FLOOR`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_dispatch
        """
        _ctx, shipment = self._setup_draft_low_margin_shipment(api)
        # DRAFT is not a dispatch from-state AND per-case margin 2830 < 5000:
        # state legality is evaluated before fiscal rules
        resp = api.dispatch_shipment(shipment["id"], RP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        shipment = get_success_data(api.get_shipment(shipment["id"], PM))
        assert shipment["status"] == "DRAFT"

    def test_fiscal_floor_fires_once_state_is_legal(self, api):
        """PRD §3.7: "From `DSD_PLANNED`, dispatch re-checks three gates: the
        run's `quality_status` must still be `PASSED` (else
        `ERR_RUN_NOT_PASSED`); freshness is re-evaluated at dispatch time — the
        shelf life minus the whole days elapsed since `completed_at` must be at
        least four, else `ERR_FRESHNESS_INSUFFICIENT`; and the margin floor
        must hold — the per-case actual margin (§3.6) must be at least the
        product's `min_margin_cents_per_case`, else `ERR_MARGIN_BELOW_FLOOR`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_dispatch
        """
        ctx = setup_passed_run(
            product_overrides={"min_margin_cents_per_case": 5000})
        shipment = create_shipment(ctx["run"]["id"], cases=1,
                                   requested_route="DSD")
        shipment = get_success_data(api.plan_shipment(shipment["id"], RP))
        assert shipment["status"] == "DSD_PLANNED"
        # state is now a legal from-state: the fiscal rule fires
        resp = api.dispatch_shipment(shipment["id"], RP)
        validate_error(resp, ApiErrorId.ERR_MARGIN_BELOW_FLOOR, 422)
