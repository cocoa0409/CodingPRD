"""Freshness dating and shipment routing: DSD vs WAREHOUSE eligibility
variants, AUTO resolution, frozen plan figures, replan, dispatch re-checks,
terminal lockdown, and case reservations."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_shipment,
    disposition_run,
    get_success_data,
    set_clock,
    setup_completed_run,
    setup_passed_run,
    validate_error,
)

PM = TEST_USERS["plant_manager_headers"]
RP = TEST_USERS["route_planner_headers"]


class TestFreshnessVariantDivergence:
    def _setup_two_auto_shipments(self, api):
        """PASSED run completed at the default clock; two AUTO shipments."""
        ctx = setup_passed_run()  # completed_at == 2026-08-01T00:00:00Z
        s2 = create_shipment(ctx["run"]["id"], cases=2,
                             requested_route="AUTO", transit_days=1)
        set_clock("2026-08-14T00:00:00Z")  # elapsed 13 -> remaining 17
        s2 = get_success_data(api.plan_shipment(s2["id"], RP))
        s1 = create_shipment(ctx["run"]["id"], cases=2,
                             requested_route="AUTO", transit_days=1)
        set_clock("2026-08-20T00:00:00Z")  # elapsed 19 -> remaining 11
        return ctx, s2, s1

    def test_auto_resolves_warehouse_at_remaining_17(self, api):
        """PRD §3.7: "Warehouse routing requires that the remaining freshness
        after subtracting `transit_days` exceed ten days — a receipt remainder
        of exactly ten days is ineligible."
        PRD §3.7: "When `requested_route` is `AUTO`, resolution prefers the
        warehouse: warehouse is selected if and only if it is
        warehouse-eligible"

        Design: Difficulty/dual_variant_calc/freshness_dsd_vs_warehouse_window_divergence
        """
        _ctx, s2, _s1 = self._setup_two_auto_shipments(api)
        # remaining 17, transit 1 -> receipt 16 > 10: warehouse-eligible
        assert s2["planned_route"] == "WAREHOUSE"
        assert s2["freshness_days_at_plan"] == 17
        assert s2["status"] == "WAREHOUSE_PLANNED"

    def test_auto_falls_back_to_dsd_at_remaining_11(self, api):
        """PRD §3.7: "otherwise direct-store delivery is selected if and only
        if it is eligible; when neither qualifies, planning is rejected with
        `ERR_FRESHNESS_INSUFFICIENT`."
        PRD §3.7: "Direct-store delivery requires at least four remaining days
        at plan time — exactly four is eligible."

        Design: Difficulty/dual_variant_calc/freshness_dsd_vs_warehouse_window_divergence
        """
        _ctx, _s2, s1 = self._setup_two_auto_shipments(api)
        # remaining 11, transit 1 -> receipt exactly 10 is not > 10, so the
        # same run data resolves DSD under the inclusive >= 4 rule
        s1 = get_success_data(api.plan_shipment(s1["id"], RP))
        assert s1["planned_route"] == "DSD"
        assert s1["freshness_days_at_plan"] == 11
        assert s1["status"] == "DSD_PLANNED"


class TestFreshnessCutoffs:
    def _setup_three_shipments(self, api):
        ctx = setup_passed_run()
        s1 = create_shipment(ctx["run"]["id"], cases=1,
                             requested_route="WAREHOUSE", transit_days=0)
        s2 = create_shipment(ctx["run"]["id"], cases=1, requested_route="DSD")
        s3 = create_shipment(ctx["run"]["id"], cases=1, requested_route="AUTO")
        return ctx, s1, s2, s3

    def test_warehouse_receipt_exactly_ten_and_auto_neither(self, api):
        """PRD §3.7: "Warehouse routing requires that the remaining freshness
        after subtracting `transit_days` exceed ten days — a receipt remainder
        of exactly ten days is ineligible."
        PRD §3.7: "An explicitly requested route that fails its eligibility bar
        is rejected with `ERR_ROUTE_INELIGIBLE`."
        PRD §3.7: "when neither qualifies, planning is rejected with
        `ERR_FRESHNESS_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/freshness_cutoff_inclusive_vs_exclusive
        """
        _ctx, s1, _s2, s3 = self._setup_three_shipments(api)
        # elapsed 20 -> remaining 10; receipt 10 - 0 = 10 is not > 10
        set_clock("2026-08-21T00:00:00Z")
        resp = api.plan_shipment(s1["id"], RP)
        validate_error(resp, ApiErrorId.ERR_ROUTE_INELIGIBLE, 422)
        # elapsed 27 -> remaining 3: warehouse 3-2=1 not > 10, DSD 3 < 4
        set_clock("2026-08-28T00:00:00Z")
        resp = api.plan_shipment(s3["id"], RP)
        validate_error(resp, ApiErrorId.ERR_FRESHNESS_INSUFFICIENT, 422)

    def test_dsd_remaining_exactly_four_plans_and_dispatches(self, api):
        """PRD §3.7: "Direct-store delivery requires at least four remaining
        days at plan time — exactly four is eligible."
        PRD §3.7: "freshness is re-evaluated at dispatch time — the shelf life
        minus the whole days elapsed since `completed_at` must be at least
        four, else `ERR_FRESHNESS_INSUFFICIENT`"

        Design: Difficulty/boundary_precision_check/freshness_cutoff_inclusive_vs_exclusive
        """
        _ctx, _s1, s2, _s3 = self._setup_three_shipments(api)
        # elapsed 26 -> remaining exactly 4: eligible at plan and at dispatch
        set_clock("2026-08-27T00:00:00Z")
        planned = get_success_data(api.plan_shipment(s2["id"], RP))
        assert planned["status"] == "DSD_PLANNED"
        assert planned["freshness_days_at_plan"] == 4
        dispatched = get_success_data(api.dispatch_shipment(s2["id"], RP))
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_at"] is not None


class TestPlanQualityGate:
    def test_plan_rejected_while_run_quality_pending(self, api):
        """PRD §3.7: "The planner's plan action requires the shipment to be
        `DRAFT` and the source run's `quality_status` to be `PASSED` —
        otherwise `ERR_RUN_NOT_PASSED`."

        Design: Difficulty/cross_entity_state_dependency/shipment_plan_gated_on_quality_passed
        """
        ctx = setup_completed_run()  # compliance-clean: quality stays PENDING
        assert ctx["run"]["quality_status"] == "PENDING"
        # creation succeeds against the COMPLETED run even while PENDING
        shipment = create_shipment(ctx["run"]["id"], cases=2,
                                   requested_route="WAREHOUSE", transit_days=1)
        resp = api.plan_shipment(shipment["id"], RP)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_PASSED, 409)
        shipment = get_success_data(api.get_shipment(shipment["id"], PM))
        assert shipment["status"] == "DRAFT"

    def test_plan_succeeds_after_quality_passed(self, api):
        """PRD §3.7: "The planner's plan action requires the shipment to be
        `DRAFT` and the source run's `quality_status` to be `PASSED` —
        otherwise `ERR_RUN_NOT_PASSED`."
        PRD §3.7: "A successful plan sets `planned_route` to `DSD` or
        `WAREHOUSE` and moves the shipment to `DSD_PLANNED` or
        `WAREHOUSE_PLANNED` respectively."

        Design: Difficulty/cross_entity_state_dependency/shipment_plan_gated_on_quality_passed
        """
        ctx = setup_completed_run()
        shipment = create_shipment(ctx["run"]["id"], cases=2,
                                   requested_route="WAREHOUSE", transit_days=1)
        resp = api.plan_shipment(shipment["id"], RP)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_PASSED, 409)
        disposition_run(ctx["run"]["id"], "PASS")
        planned = get_success_data(api.plan_shipment(shipment["id"], RP))
        assert planned["status"] == "WAREHOUSE_PLANNED"
        assert planned["planned_route"] == "WAREHOUSE"
        # planned at the default clock, the same instant as completion
        assert planned["freshness_days_at_plan"] == 30


class TestFreshnessFloor:
    def test_freshness_floor_partial_day_not_counted(self, api):
        """PRD §3.7: "Planning freezes `freshness_days_at_plan`: the product's
        `shelf_life_days` minus the number of whole days elapsed between the
        run's `completed_at` and the plan time on the logical clock, where any
        partial day is discarded."

        Design: Corner/calculations/freshness_floor_partial_day_not_counted
        """
        ctx = setup_passed_run(
            start="2026-08-01T00:00:00Z", end="2026-08-01T23:00:00Z",
            completed_at="2026-08-01T12:00:00Z")
        shipment = create_shipment(ctx["run"]["id"], cases=1,
                                   requested_route="AUTO", transit_days=2)
        # 23h59m after completion floors to 0 whole days elapsed
        set_clock("2026-08-02T11:59:59Z")
        planned = get_success_data(api.plan_shipment(shipment["id"], RP))
        assert planned["freshness_days_at_plan"] == 30
        # 30 - 2 = 28 > 10: warehouse-eligible
        assert planned["planned_route"] == "WAREHOUSE"


class TestReplan:
    def test_shipment_replan_clears_route_and_freshness(self, api):
        """PRD §3.7: "replanning a shipment in either planned state returns it
        to `DRAFT` and clears both `planned_route` and `freshness_days_at_plan`
        to null, ready for a fresh plan."

        Design: Corner/state_machines/shipment_replan_clears_route_and_freshness
        """
        ctx = setup_passed_run()
        shipment = create_shipment(ctx["run"]["id"], cases=1,
                                   requested_route="AUTO", transit_days=1)
        planned = get_success_data(api.plan_shipment(shipment["id"], RP))
        # remaining 30, transit 1 -> receipt 29 > 10: warehouse branch
        assert planned["status"] == "WAREHOUSE_PLANNED"
        assert planned["planned_route"] == "WAREHOUSE"
        assert planned["freshness_days_at_plan"] == 30
        replanned = get_success_data(api.replan_shipment(shipment["id"], RP))
        assert replanned["status"] == "DRAFT"
        assert replanned["planned_route"] is None
        assert replanned["freshness_days_at_plan"] is None
        # the branching fork is re-enterable
        replanned = get_success_data(api.plan_shipment(shipment["id"], RP))
        assert replanned["status"] == "WAREHOUSE_PLANNED"
        assert replanned["planned_route"] == "WAREHOUSE"


class TestTerminalLockdown:
    def test_terminal_lockdown_dispatched_shipment(self, api):
        """PRD §3.7: "Successful dispatch stamps `dispatched_at` and moves the
        shipment to `DISPATCHED`, terminal alongside `CANCELLED`."
        PRD §2.9: "the target entity occupies a from-state of the invoked
        transition, terminal entities reject all further transitions with
        `ERR_ALREADY_TERMINAL`"

        Design: Corner/state_machines/terminal_lockdown_dispatched_shipment
        """
        ctx = setup_passed_run()
        shipment = create_shipment(ctx["run"]["id"], cases=1,
                                   requested_route="DSD")
        get_success_data(api.plan_shipment(shipment["id"], RP))
        dispatched = get_success_data(api.dispatch_shipment(shipment["id"], RP))
        assert dispatched["status"] == "DISPATCHED"
        resp = api.dispatch_shipment(shipment["id"], RP)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        resp = api.cancel_shipment(shipment["id"], RP)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        shipment = get_success_data(api.get_shipment(shipment["id"], PM))
        assert shipment["status"] == "DISPATCHED"


class TestCaseReservation:
    def test_shipment_cases_exceed_unrouted_rejected(self, api):
        """PRD §3.7: "The source run must be `COMPLETED` — anything else is
        `ERR_INVALID_STATE` — and the reservation must fit inside the run's
        `cases_unrouted` balance, else `ERR_CASES_UNAVAILABLE`."

        Design: Corner/validations/shipment_cases_exceed_unrouted_rejected
        """
        ctx = setup_completed_run()  # 10 accepted cases
        create_shipment(ctx["run"]["id"], cases=3, requested_route="DSD")
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["cases_unrouted"] == 7
        resp = api.create_shipment(
            {"run_id": ctx["run"]["id"], "cases": 8, "requested_route": "DSD"},
            RP)
        validate_error(resp, ApiErrorId.ERR_CASES_UNAVAILABLE, 422)
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["cases_unrouted"] == 7, "the first reservation is untouched"
