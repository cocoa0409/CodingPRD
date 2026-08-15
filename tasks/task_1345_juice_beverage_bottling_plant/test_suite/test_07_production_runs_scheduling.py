"""Production run lifecycle: quoting, confirming, scheduling gates, OCC, start."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, factories,
    create_customer, create_formula, create_tank, create_line,
    create_container_lot, create_zone, create_released_batch,
    create_qa_passed_batch, quote_run, confirm_run, schedule_run, set_clock,
    submit_label, setup_pipeline, setup_scheduled_run,
    plan_batch, blend_and_record, qa_verdict,
)

# Module-level alias of the session-scoped `api` fixture (conftest returns
# the same object) so module/class helpers can call the client without
# declaring the fixture parameter.
api = api_client


PM = TEST_USERS["plant_manager_headers"]
DEV = TEST_USERS["product_developer_headers"]
REV = TEST_USERS["label_reviewer_headers"]
PLAN = TEST_USERS["production_planner_headers"]
FIN = TEST_USERS["finance_clerk_headers"]
QA = TEST_USERS["qa_inspector_headers"]


class TestInitialStates:
    def test_run_and_order_initial_states(self, api):
        """PRD §3.7: "A quoted run stands in `QUOTED` with its invoice dimension in
        `NOT_INVOICED`." and §3.9: "The order is born in `PLACED` with a
        channel-derived `min_shelf_life_days`"

        Design: Corner/entities/run_and_order_initial_states
        """
        customer = create_customer()
        formula = create_formula(customer["id"], approve=False)
        resp = api.create_production_run(
            factories.create_production_run_payload(customer["id"], formula["id"]), PLAN)
        run = validate_success(resp, 201)
        assert run["production_status"] == "QUOTED"
        assert run["invoice_status"] == "NOT_INVOICED"
        order = get_success_data(api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer["id"], formula["id"], channel="CLUB",
                requested_delivery_date="2026-08-15", units_requested=240),
            TEST_USERS["customer_service_rep_headers"]))
        assert order["status"] == "PLACED"
        assert order["allocated_units"] == 0
        assert order["allocations"] == []


class TestRunInvalidTransitions:
    def test_quoted_accepts_only_confirm_or_cancel(self, api):
        """PRD §3.7: "Confirming the quote (`QUOTED` → `CONFIRMED`) stacks three
        gates on top of the state check (`ERR_RUN_STATE_INVALID` otherwise)" and
        §3.7: "A planner may also cancel outright from `QUOTED`, `CONFIRMED`,
        `SCHEDULED`, `BLOCKED_SUPPLY`, or `BLOCKED_LABEL` — any other state draws
        `ERR_RUN_STATE_INVALID`"

        Design: Corner/state_machines/production_run_invalid_transition_sweep
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank = create_tank()
        batch = create_qa_passed_batch(formula, tank, quantity_liters=1000)
        line = create_line()
        zone = create_zone()
        run = quote_run(customer["id"], formula["id"])
        rid = run["id"]
        validate_error(api.start_run(rid, PLAN), ApiErrorId.ERR_RUN_STATE_INVALID)
        validate_error(api.complete_run(
            rid, factories.complete_run_payload(zone["id"], actual_units_filled=100), PLAN),
            ApiErrorId.ERR_RUN_STATE_INVALID)
        validate_error(api.finalize_invoice(rid, FIN), ApiErrorId.ERR_RUN_STATE_INVALID)
        # schedule from QUOTED with the CURRENT version: OCC passes, state gate fires
        resp = api.schedule_run(
            rid, factories.schedule_run_payload(batch["id"], line["id"], run["version"]), PLAN)
        validate_error(resp, ApiErrorId.ERR_RUN_STATE_INVALID)
        confirmed = get_success_data(api.confirm_run(rid, PLAN))
        assert confirmed["production_status"] == "CONFIRMED"

    def test_confirm_not_idempotent_and_cancelled_terminal(self, api):
        """PRD §3.7: "A planner may also cancel outright from `QUOTED`,
        `CONFIRMED`, `SCHEDULED`, `BLOCKED_SUPPLY`, or `BLOCKED_LABEL` — any other
        state draws `ERR_RUN_STATE_INVALID` — landing the run terminally in
        `CANCELLED`."

        Design: Corner/state_machines/production_run_invalid_transition_sweep
        """
        customer = create_customer()
        formula = create_formula(customer["id"])
        run = quote_run(customer["id"], formula["id"])
        rid = run["id"]
        get_success_data(api.confirm_run(rid, PLAN))
        validate_error(api.confirm_run(rid, PLAN), ApiErrorId.ERR_RUN_STATE_INVALID)
        cancelled = get_success_data(api.cancel_run(rid, PLAN))
        assert cancelled["production_status"] == "CANCELLED"
        validate_error(api.cancel_run(rid, PLAN), ApiErrorId.ERR_RUN_STATE_INVALID)
        validate_error(api.confirm_run(rid, PLAN), ApiErrorId.ERR_RUN_STATE_INVALID)


class TestMinimumRunBoundary:
    def test_planned_exactly_at_minimum_confirms(self, api):
        """PRD §3.7: "`planned_units` must reach the customer's
        `minimum_run_units` — a run planned at exactly the minimum is acceptable,
        while anything smaller is refused with `ERR_MINIMUM_RUN_NOT_MET`."

        Design: Difficulty/boundary_precision_check/minimum_run_exactly_met_vs_one_below
        """
        customer = create_customer(minimum_run_units=500)
        formula = create_formula(customer["id"])
        run_a = quote_run(customer["id"], formula["id"], planned_units=500)
        confirmed = get_success_data(api.confirm_run(run_a["id"], PLAN))
        assert confirmed["production_status"] == "CONFIRMED"

    def test_planned_one_below_minimum_rejected(self, api):
        """PRD §3.7: "a run planned at exactly the minimum is acceptable, while
        anything smaller is refused with `ERR_MINIMUM_RUN_NOT_MET`."

        Design: Difficulty/boundary_precision_check/minimum_run_exactly_met_vs_one_below
        """
        customer = create_customer(minimum_run_units=500)
        formula = create_formula(customer["id"])
        run_b = quote_run(customer["id"], formula["id"], planned_units=499)
        resp = api.confirm_run(run_b["id"], PLAN)
        validate_error(resp, ApiErrorId.ERR_MINIMUM_RUN_NOT_MET)
        assert resp.status_code == 422


class TestScheduleBatchGate:
    def _confirmed_run_with_unreleased_batch(self):
        """CONFIRMED run + a batch that stopped at QA_PASSED (never processed)."""
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank = create_tank()
        batch = create_qa_passed_batch(formula, tank)
        line = create_line()
        clot = create_container_lot()
        run = confirm_run(quote_run(customer["id"], formula["id"], planned_units=1000)["id"])
        return {"customer": customer, "formula": formula, "batch": batch,
                "line": line, "clot": clot, "run": run}

    def test_schedule_with_unreleased_batch_rejected(self, api):
        """PRD §3.7: "The batch must stand in `RELEASED` and must belong to the
        run's formula — a batch of any other state or any other formula is refused
        with `ERR_BATCH_NOT_RELEASED`"

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_released_batch
        """
        ctx = self._confirmed_run_with_unreleased_batch()
        resp = api.schedule_run(
            ctx["run"]["id"],
            factories.schedule_run_payload(
                ctx["batch"]["id"], ctx["line"]["id"], ctx["run"]["version"]), PLAN)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_RELEASED)
        assert resp.status_code == 409

    def test_failed_schedule_reserves_nothing(self, api):
        """PRD §3.7: "it must cover the planned count inflated by five percent and
        rounded up to a whole unit, else the schedule is refused with
        `ERR_CONTAINER_SUPPLY_INSUFFICIENT` and nothing is reserved." (the failed
        schedule applies nothing.)

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_released_batch
        """
        ctx = self._confirmed_run_with_unreleased_batch()
        validate_error(api.schedule_run(
            ctx["run"]["id"],
            factories.schedule_run_payload(
                ctx["batch"]["id"], ctx["line"]["id"], ctx["run"]["version"]), PLAN),
            ApiErrorId.ERR_BATCH_NOT_RELEASED)
        run_after = get_success_data(api.get_production_run(ctx["run"]["id"], PM))
        assert run_after["production_status"] == "CONFIRMED"
        lot_after = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        assert lot_after["quantity_reserved"] == 0


class TestScheduleLabelSafetyPriority:
    def _setup_label_review_plus_condemned_batch(self):
        """CONFIRMED run; its candidate batch CONDEMNED; the formula re-submitted
        so it stands in LABEL_REVIEW — schedule violates both the label-safety
        gate and the batch-referential gate."""
        customer = create_customer()
        formula = create_formula(customer["id"])
        run = confirm_run(quote_run(customer["id"], formula["id"], planned_units=1000)["id"])
        tank = create_tank()
        # 14.0 is outside the 0.3 band; fail and condemn the batch
        batch = plan_batch(formula["id"], tank["id"], quantity_liters=2000)
        blend_and_record(batch["id"], 14.0)
        qa_verdict(batch["id"], "FAIL")
        condemned = get_success_data(api.condemn_batch(batch["id"], QA))
        assert condemned["status"] == "CONDEMNED"
        line = create_line()
        create_container_lot()
        # re-submit the approved formula: APPROVED -> LABEL_REVIEW
        submit_label(formula["id"])
        return {"run": run, "batch": batch, "line": line, "formula": formula}

    def test_label_safety_error_beats_batch_referential(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline of check
        categories, evaluated in the order below; when several checks would fail,
        the earliest category's error is the one returned." (label/quality safety
        gates, category 6, precede referential linkability, category 7.)

        Design: Difficulty/priority_pair_validation_conflict/schedule_label_safety_beats_batch_referential
        """
        ctx = self._setup_label_review_plus_condemned_batch()
        resp = api.schedule_run(
            ctx["run"]["id"],
            factories.schedule_run_payload(
                ctx["batch"]["id"], ctx["line"]["id"], ctx["run"]["version"]), PLAN)
        error = validate_error(resp, ApiErrorId.ERR_LABEL_NOT_APPROVED)
        assert error["error_id"] != ApiErrorId.ERR_BATCH_NOT_RELEASED

    def test_failed_schedule_leaves_run_confirmed(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline of check
        categories, evaluated in the order below; when several checks would fail,
        the earliest category's error is the one returned."

        Design: Difficulty/priority_pair_validation_conflict/schedule_label_safety_beats_batch_referential
        """
        ctx = self._setup_label_review_plus_condemned_batch()
        validate_error(api.schedule_run(
            ctx["run"]["id"],
            factories.schedule_run_payload(
                ctx["batch"]["id"], ctx["line"]["id"], ctx["run"]["version"]), PLAN),
            ApiErrorId.ERR_LABEL_NOT_APPROVED)
        run_after = get_success_data(api.get_production_run(ctx["run"]["id"], PM))
        assert run_after["production_status"] == "CONFIRMED"


class TestScheduleGateSweep:
    def _sweep_setup(self):
        """Two RELEASED batches, a PET_473-only line and a GLASS_355-only line,
        one QC_PASSED lot of 5000 PET_473, and five CONFIRMED runs."""
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank1 = create_tank()
        batch1 = create_released_batch(formula, tank1)
        tank2 = create_tank()
        batch2 = create_released_batch(formula, tank2)
        line1 = create_line(supported_container_types=("PET_473",))
        line2 = create_line(supported_container_types=("GLASS_355",))
        clot = create_container_lot(quantity_received=5000)
        runs = {}
        for key, planned in (("ra", 500), ("rb", 500), ("rc", 5000),
                             ("rd", 1000), ("re", 500)):
            runs[key] = confirm_run(quote_run(customer["id"], formula["id"],
                                              planned_units=planned)["id"])
        return {"customer": customer, "formula": formula, "batch1": batch1,
                "batch2": batch2, "line1": line1, "line2": line2, "clot": clot,
                "runs": runs}

    def test_unsupported_container_and_invalid_window_gates(self, api):
        """PRD §3.7: "it must list the run's `container_type` among its
        `supported_container_types` (else `ERR_LINE_UNSUPPORTED_CONTAINER`), and
        the window's end must be strictly after its start (else
        `ERR_INVALID_WINDOW`)."

        Design: Corner/endpoints/schedule_gate_sweep
        """
        ctx = self._sweep_setup()
        ra, rb = ctx["runs"]["ra"], ctx["runs"]["rb"]
        # PET_473 run onto a GLASS_355-only line
        resp = api.schedule_run(
            ra["id"],
            factories.schedule_run_payload(
                ctx["batch1"]["id"], ctx["line2"]["id"], ra["version"]), PLAN)
        validate_error(resp, ApiErrorId.ERR_LINE_UNSUPPORTED_CONTAINER)
        assert resp.status_code == 422
        # end == start is not strictly greater
        resp = api.schedule_run(
            rb["id"],
            factories.schedule_run_payload(
                ctx["batch1"]["id"], ctx["line1"]["id"], rb["version"],
                scheduled_start_at="2026-08-11T08:00:00Z",
                scheduled_end_at="2026-08-11T08:00:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
        assert resp.status_code == 422
        # failed schedules change nothing
        assert get_success_data(api.get_production_run(ra["id"], PM))["production_status"] == "CONFIRMED"

    def test_supply_shortfall_and_batch_link_gates(self, api):
        """PRD §3.7: "The pool is the sum of `quantity_available` over all
        `QC_PASSED` lots of the run's container type; it must cover the planned
        count inflated by five percent and rounded up to a whole unit, else the
        schedule is refused with `ERR_CONTAINER_SUPPLY_INSUFFICIENT` and nothing
        is reserved." and "it must be unlinked, a non-null `linked_run_id` drawing
        `ERR_BATCH_ALREADY_LINKED`."

        Design: Corner/endpoints/schedule_gate_sweep
        """
        ctx = self._sweep_setup()
        rc, rd, re = ctx["runs"]["rc"], ctx["runs"]["rd"], ctx["runs"]["re"]
        # need ceil(5000 * 1.05) == 5250 > 5000 available
        resp = api.schedule_run(
            rc["id"],
            factories.schedule_run_payload(
                ctx["batch1"]["id"], ctx["line1"]["id"], rc["version"]), PLAN)
        validate_error(resp, ApiErrorId.ERR_CONTAINER_SUPPLY_INSUFFICIENT)
        assert resp.status_code == 409
        lot = get_success_data(api.get_container_lot(ctx["clot"]["id"], PM))
        assert lot["quantity_reserved"] == 0  # atomic: nothing reserved
        # RD schedules successfully and links batch1
        scheduled = schedule_run(rd["id"], ctx["batch1"]["id"], ctx["line1"]["id"])
        assert scheduled["production_status"] == "SCHEDULED"
        assert scheduled["label_version_pinned"] == 1  # 0 at birth + 1 approval
        # floor(1960.0 * 1000 / 473) == 4143
        assert scheduled["theoretical_units"] == 4143
        # batch1 is now linked; supply is ample, so the link gate fires alone
        resp = api.schedule_run(
            re["id"],
            factories.schedule_run_payload(
                ctx["batch1"]["id"], ctx["line1"]["id"], re["version"],
                scheduled_start_at="2026-08-11T13:00:00Z",
                scheduled_end_at="2026-08-11T17:00:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_BATCH_ALREADY_LINKED)


class TestRunStartWindow:
    def _two_scheduled_runs(self):
        customer = create_customer()
        formula = create_formula(customer["id"])
        tank1 = create_tank()
        batch1 = create_released_batch(formula, tank1)
        tank2 = create_tank()
        batch2 = create_released_batch(formula, tank2)
        line = create_line()
        create_container_lot()
        run1 = confirm_run(quote_run(customer["id"], formula["id"], planned_units=500)["id"])
        run1 = schedule_run(run1["id"], batch1["id"], line["id"],
                            "2026-08-11T08:00:00Z", "2026-08-11T12:00:00Z")
        run2 = confirm_run(quote_run(customer["id"], formula["id"], planned_units=500)["id"])
        run2 = schedule_run(run2["id"], batch2["id"], line["id"],
                            "2026-08-11T13:00:00Z", "2026-08-11T17:00:00Z")
        return run1, run2

    def test_start_before_window_rejected_at_start_allowed(self, api):
        """PRD §3.7: "the logical clock must read at or after `scheduled_start_at`
        and strictly before `scheduled_end_at`, else `ERR_RUN_WINDOW_NOT_ACTIVE`"

        Design: Corner/validations/run_start_window_half_open_edges
        """
        run1, _ = self._two_scheduled_runs()
        set_clock("2026-08-11T07:59:00Z")
        resp = api.start_run(run1["id"], PLAN)
        validate_error(resp, ApiErrorId.ERR_RUN_WINDOW_NOT_ACTIVE)
        set_clock("2026-08-11T08:00:00Z")
        started = get_success_data(api.start_run(run1["id"], PLAN))
        assert started["production_status"] == "IN_PRODUCTION"

    def test_start_at_window_end_rejected(self, api):
        """PRD §2.4: "Bottling-line bookings are **half-open intervals**: a run
        booked from its `scheduled_start_at` to its `scheduled_end_at` occupies
        the line from the start inclusive up to but not including the end." and
        §3.7: "the logical clock must read at or after `scheduled_start_at` and
        strictly before `scheduled_end_at`, else `ERR_RUN_WINDOW_NOT_ACTIVE`"

        Design: Corner/validations/run_start_window_half_open_edges
        """
        _, run2 = self._two_scheduled_runs()
        set_clock("2026-08-11T17:00:00Z")
        resp = api.start_run(run2["id"], PLAN)
        validate_error(resp, ApiErrorId.ERR_RUN_WINDOW_NOT_ACTIVE)
        assert get_success_data(api.get_production_run(run2["id"], PM))["production_status"] == "SCHEDULED"


class TestStartLabelStalePriority:
    def _scheduled_run_then_label_bump(self):
        """Run SCHEDULED with label_version_pinned == 1; the formula is then
        re-submitted and re-approved so its label_version becomes 2."""
        ctx = setup_scheduled_run()
        formula_id = ctx["formula"]["id"]
        review = submit_label(formula_id)
        get_success_data(api.approve_label_review(review["id"], REV))
        return ctx

    def test_stale_label_error_beats_window_error(self, api):
        """PRD §2.6: "Every request is validated against a fixed pipeline of check
        categories, evaluated in the order below; when several checks would fail,
        the earliest category's error is the one returned." (label/quality safety
        gates, category 6, precede clock-relative gates, category 9.)

        Design: Difficulty/priority_pair_validation_conflict/start_label_stale_beats_window_temporal
        """
        ctx = self._scheduled_run_then_label_bump()
        # clock OUTSIDE the window as well: both gates fail, safety wins
        set_clock("2026-08-10T09:00:00Z")
        resp = api.start_run(ctx["run"]["id"], PLAN)
        error = validate_error(resp, ApiErrorId.ERR_LABEL_VERSION_STALE)
        assert error["error_id"] != ApiErrorId.ERR_RUN_WINDOW_NOT_ACTIVE

    def test_stale_start_leaves_run_scheduled_with_old_pin(self, api):
        """PRD §3.7: "the pinned label version must still equal the formula's
        current `label_version` — a label approval in between has bumped it, and
        the start is refused with `ERR_LABEL_VERSION_STALE`"

        Design: Difficulty/priority_pair_validation_conflict/start_label_stale_beats_window_temporal
        """
        ctx = self._scheduled_run_then_label_bump()
        set_clock("2026-08-10T09:00:00Z")
        validate_error(api.start_run(ctx["run"]["id"], PLAN),
                       ApiErrorId.ERR_LABEL_VERSION_STALE)
        run_after = get_success_data(api.get_production_run(ctx["run"]["id"], PM))
        assert run_after["production_status"] == "SCHEDULED"
        assert run_after["label_version_pinned"] == 1
        formula_after = get_success_data(api.get_formula(ctx["formula"]["id"], PM))
        assert formula_after["label_version"] == 2


class TestRunScheduleOcc:
    def test_stale_schedule_rejected_412(self, api):
        """PRD §2.7: "Scheduling or re-scheduling a production run (`POST
        /v1/production-runs/{id}/schedule`) requires
        `expected_production_run_version` equal to the run's current `version`."
        and "the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no
        part of the write is applied."

        Design: Corner/cross_cutting_layers/occ_run_schedule_stale
        """
        ctx = setup_pipeline()
        run = confirm_run(ctx["run"]["id"])
        scheduled = schedule_run(run["id"], ctx["batch"]["id"], ctx["line"]["id"])
        assert scheduled["production_status"] == "SCHEDULED"
        assert scheduled["version"] == run["version"] + 1
        # replay with the pre-schedule version
        resp = api.schedule_run(
            run["id"],
            factories.schedule_run_payload(
                ctx["batch"]["id"], ctx["line"]["id"], run["version"],
                scheduled_start_at="2026-08-11T13:00:00Z",
                scheduled_end_at="2026-08-11T17:00:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412

    def test_current_version_reaches_state_gate(self, api):
        """PRD §3.7: "A successful scheduling pins `label_version_pinned` to the
        formula's current `label_version`" and §3.7: scheduling runs "from
        `CONFIRMED`, or from `BLOCKED_SUPPLY` when a condemned batch forced a
        re-plan" — a run already in `SCHEDULED` fails the state check once OCC has
        passed.

        Design: Corner/cross_cutting_layers/occ_run_schedule_stale
        """
        ctx = setup_pipeline()
        run = confirm_run(ctx["run"]["id"])
        scheduled = schedule_run(run["id"], ctx["batch"]["id"], ctx["line"]["id"])
        assert scheduled["label_version_pinned"] == 1
        # current version passes OCC; SCHEDULED is not a schedulable state
        resp = api.schedule_run(
            run["id"],
            factories.schedule_run_payload(
                ctx["batch"]["id"], ctx["line"]["id"], scheduled["version"],
                scheduled_start_at="2026-08-11T13:00:00Z",
                scheduled_end_at="2026-08-11T17:00:00Z"), PLAN)
        validate_error(resp, ApiErrorId.ERR_RUN_STATE_INVALID)
        assert resp.status_code == 409


class TestFormulaCustomerMismatch:
    def test_run_rejects_formula_of_other_customer(self, api):
        """PRD §3.7: "The formula must belong to the customer being quoted — its
        `customer_id` must equal the run's — else the quote is refused with
        `ERR_FORMULA_CUSTOMER_MISMATCH`."

        Design: Corner/validations/formula_customer_mismatch_on_run_and_order
        """
        customer_a = create_customer(name="MmA")
        customer_b = create_customer(name="MmB")
        formula_b = create_formula(customer_b["id"], approve=False)
        resp = api.create_production_run(
            factories.create_production_run_payload(customer_a["id"], formula_b["id"]),
            PLAN)
        validate_error(resp, ApiErrorId.ERR_FORMULA_CUSTOMER_MISMATCH)
        assert resp.status_code == 422

    def test_order_rejects_formula_of_other_customer(self, api):
        """PRD §3.9: "The formula's owning customer must match the order's
        customer, else `ERR_FORMULA_CUSTOMER_MISMATCH`."

        Design: Corner/validations/formula_customer_mismatch_on_run_and_order
        """
        customer_a = create_customer(name="MmA")
        customer_b = create_customer(name="MmB")
        formula_b = create_formula(customer_b["id"], approve=False)
        resp = api.create_shipment_order(
            factories.create_shipment_order_payload(
                customer_a["id"], formula_b["id"], channel="DIRECT_RETAIL",
                requested_delivery_date="2026-08-10", units_requested=100),
            TEST_USERS["customer_service_rep_headers"])
        validate_error(resp, ApiErrorId.ERR_FORMULA_CUSTOMER_MISMATCH)
        assert resp.status_code == 422
