"""Filling-line scheduling: half-open occupancy, the changeover matrix, run
start gates, completion settlement, the line cleaning cycle, and the order
cancellation cascade."""
from test_helpers import (
    ApiErrorId,
    abort_run,
    approve_label_artwork,
    assert_line,
    assert_lot,
    assert_order,
    assert_run,
    assert_shortfall,
    allocate_lots,
    allocation_item,
    cancel_order,
    complete_run,
    confirm_order,
    create_active_formula,
    create_batch,
    create_component,
    create_customer,
    create_customer_supplied_component,
    create_line,
    create_lot,
    create_order,
    declare_shortfall,
    finish_cleaning,
    in_progress_run_ctx,
    mixing_batch_ctx,
    record_ipc_check,
    release_batch,
    schedule_run,
    scheduled_run_ctx,
    start_mixing,
    start_run,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PP, QA1, QA2


def _two_active_formulas(customer_id, component_id, second_component_id=None,
                         first_overrides=None, second_overrides=None):
    """Build two ACTIVE formulas for changeover scenarios."""
    f1 = create_active_formula(customer_id, component_id=component_id, **(first_overrides or {}))
    ingredients2 = None
    if second_component_id is not None:
        ingredients2 = [{"inci_name": "AQUA", "component_id": second_component_id, "percentage": 100}]
    f2 = create_active_formula(customer_id, ingredients=ingredients2, component_id=component_id,
                               **(second_overrides or {}))
    return f1, f2


def _confirmed_order_with_batch(customer_id, formula_id, units=2000, batch_kg=100):
    order = create_order(customer_id, formula_id, units)
    confirm_order(order["id"], customer_id)
    batch = create_batch(order["id"], batch_kg)
    return order, batch


class TestChangeoverMultiInput:
    def test_changeover_multi_input_branch(self, api, production_planner_headers):
        """PRD §3.8: "The base requirement is zero minutes when both runs use the
        same formula; 15 minutes when the two formulas share a `product_class`
        and neither carries an `allergen_flag`; 45 minutes when their product
        classes differ and neither is allergen-flagged; and 120 minutes whenever
        either formula is allergen-flagged."
        PRD §3.8: "When the previous run's formula contains an ingredient whose
        component is of kind `BULK_FRAGRANCE` and the two runs use different
        formulas, 30 minutes of fragrance carryover are added to the base."
        PRD §3.8: "The new run's `scheduled_start` must fall at or after the
        previous run's `scheduled_end` plus the requirement, with a gap exactly
        equal to the requirement allowed; a smaller gap is rejected with
        `ERR_CHANGEOVER_GAP_VIOLATION` (HTTP 409)."

        Design: Difficulty/combinatorial_formula/changeover_multi_input_branch
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        parfum = create_component(name="Parfum", kind="BULK_FRAGRANCE",
                                  standard_cost_per_kg_cents=5000)
        f1 = create_active_formula(customer["id"], ingredients=[
            {"inci_name": "AQUA", "component_id": water["id"], "percentage": 95},
            {"inci_name": "PARFUM", "component_id": parfum["id"], "percentage": 5},
        ], name="F1", product_class="SKIN")
        f2 = create_active_formula(customer["id"], component_id=water["id"],
                                   name="F2", product_class="HAIR")
        order1, batch1 = _confirmed_order_with_batch(customer["id"], f1["id"])
        order2, batch2 = _confirmed_order_with_batch(customer["id"], f2["id"])
        line = create_line()
        schedule_run(order1["id"], line["id"], batch1["id"], 2000,
                     "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")

        # DIFFERENT_CLASS base 45 + fragrance carryover 30 = 75 required.
        resp = api.create_run(order2["id"], {
            "line_id": line["id"], "batch_id": batch2["id"],
            "scheduled_start": "2026-05-10T10:30:00Z", "scheduled_end": "2026-05-10T12:00:00Z",
            "planned_units": 1000}, PP)
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_GAP_VIOLATION, 409)

        accepted = schedule_run(order2["id"], line["id"], batch2["id"], 1000,
                                "2026-05-10T11:15:00Z", "2026-05-10T12:30:00Z")
        assert_run(accepted)
        assert accepted["changeover_minutes_required"] == 75

    def test_changeover_different_class_no_fragrance(self, api, production_planner_headers):
        """PRD §3.8: "45 minutes when their product classes differ and neither is
        allergen-flagged".

        Design: Difficulty/combinatorial_formula/changeover_multi_input_branch
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        f1, f2 = _two_active_formulas(customer["id"], water["id"],
                                      first_overrides={"name": "F1", "product_class": "SKIN"},
                                      second_overrides={"name": "F2", "product_class": "HAIR"})
        order1, batch1 = _confirmed_order_with_batch(customer["id"], f1["id"])
        order2, batch2 = _confirmed_order_with_batch(customer["id"], f2["id"])
        line = create_line()
        schedule_run(order1["id"], line["id"], batch1["id"], 2000,
                     "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")

        run2 = schedule_run(order2["id"], line["id"], batch2["id"], 1000,
                            "2026-05-10T10:45:00Z", "2026-05-10T11:30:00Z")
        assert_run(run2)
        assert run2["changeover_minutes_required"] == 45


class TestChangeoverBoundary:
    def test_changeover_gap_exactly_equal_passes(self, api, production_planner_headers):
        """PRD §3.8: "The new run's `scheduled_start` must fall at or after the
        previous run's `scheduled_end` plus the requirement, with a gap exactly
        equal to the requirement allowed; a smaller gap is rejected with
        `ERR_CHANGEOVER_GAP_VIOLATION` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/changeover_gap_exactly_equal_passes
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        f1, f2 = _two_active_formulas(customer["id"], water["id"],
                                      first_overrides={"name": "F1"},
                                      second_overrides={"name": "F2"})
        order1, batch1 = _confirmed_order_with_batch(customer["id"], f1["id"])
        order2, batch2 = _confirmed_order_with_batch(customer["id"], f2["id"])
        line = create_line()
        schedule_run(order1["id"], line["id"], batch1["id"], 2000,
                     "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")

        # Same class, no allergen, no fragrance: requirement is 15 minutes.
        resp = api.create_run(order2["id"], {
            "line_id": line["id"], "batch_id": batch2["id"],
            "scheduled_start": "2026-05-10T10:14:00Z", "scheduled_end": "2026-05-10T11:00:00Z",
            "planned_units": 1000}, PP)
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_GAP_VIOLATION, 409)

        accepted = schedule_run(order2["id"], line["id"], batch2["id"], 1000,
                                "2026-05-10T10:15:00Z", "2026-05-10T11:00:00Z")
        assert_run(accepted)
        assert accepted["changeover_minutes_required"] == 15

    def test_first_run_on_line_requires_no_changeover(self, api, production_planner_headers):
        """PRD §3.8: "when no such run exists, `changeover_minutes_required` is
        zero and no gap check applies."

        Design: Difficulty/boundary_precision_check/changeover_gap_exactly_equal_passes
        """
        ctx = scheduled_run_ctx()
        assert_run(ctx["run"])
        assert ctx["run"]["changeover_minutes_required"] == 0


class TestLineWindowAdjacency:
    def test_line_window_half_open_adjacency(self, api, production_planner_headers):
        """PRD §3.8: "Occupancy treats each window as half-open: the new window
        must not intersect any run on the same line standing `SCHEDULED` or
        `IN_PROGRESS`, but touching endpoints are allowed — a run that ends
        exactly when the next begins does not conflict; a genuine overlap is
        rejected with `ERR_LINE_OCCUPIED` (HTTP 409)."
        PRD §3.8: "The base requirement is zero minutes when both runs use the
        same formula".

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=water["id"])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        batch1 = create_batch(order["id"], 50)
        batch2 = create_batch(order["id"], 50)
        line = create_line()
        schedule_run(order["id"], line["id"], batch1["id"], 1000,
                     "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")

        resp = api.create_run(order["id"], {
            "line_id": line["id"], "batch_id": batch2["id"],
            "scheduled_start": "2026-05-10T09:59:00Z", "scheduled_end": "2026-05-10T11:00:00Z",
            "planned_units": 1000}, PP)
        validate_error(resp, ApiErrorId.ERR_LINE_OCCUPIED, 409)

        adjacent = schedule_run(order["id"], line["id"], batch2["id"], 1000,
                                "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
        assert_run(adjacent)
        assert adjacent["changeover_minutes_required"] == 0

    def test_aborted_run_does_not_block_window(self, api, production_planner_headers):
        """PRD §3.8: "the new window must not intersect any run on the same line
        standing `SCHEDULED` or `IN_PROGRESS`".
        PRD §3.8: "Aborting a `SCHEDULED` run moves it to `ABORTED` and releases
        its line window without any line state change."

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=water["id"])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        batch1 = create_batch(order["id"], 50)
        batch2 = create_batch(order["id"], 50)
        line = create_line()
        run1 = schedule_run(order["id"], line["id"], batch1["id"], 1000,
                            "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")
        aborted = abort_run(run1["id"])
        assert aborted["status"] == "ABORTED"

        run2 = schedule_run(order["id"], line["id"], batch2["id"], 1000,
                            "2026-05-10T08:00:00Z", "2026-05-10T09:00:00Z")
        assert_run(run2)
        assert run2["status"] == "SCHEDULED"


class TestAllergenChangeoverBuffer:
    def test_line_changeover_allergen_buffer(self, api, production_planner_headers):
        """PRD §3.8: "and 120 minutes whenever either formula is
        allergen-flagged."
        PRD §3.8: "When the previous run's formula contains an ingredient whose
        component is of kind `BULK_FRAGRANCE` and the two runs use different
        formulas, 30 minutes of fragrance carryover are added to the base."
        PRD §3.8: "a smaller gap is rejected with
        `ERR_CHANGEOVER_GAP_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/line_changeover_allergen_buffer
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        parfum = create_component(name="Parfum", kind="BULK_FRAGRANCE",
                                  standard_cost_per_kg_cents=5000)
        f1 = create_active_formula(customer["id"], ingredients=[
            {"inci_name": "AQUA", "component_id": water["id"], "percentage": 95},
            {"inci_name": "PARFUM", "component_id": parfum["id"], "percentage": 5},
        ], name="F1", product_class="SKIN", allergen_flag=True)
        f2 = create_active_formula(customer["id"], component_id=water["id"],
                                   name="F2", product_class="SKIN", allergen_flag=False)
        order1, batch1 = _confirmed_order_with_batch(customer["id"], f1["id"])
        order2, batch2 = _confirmed_order_with_batch(customer["id"], f2["id"])
        line = create_line()
        schedule_run(order1["id"], line["id"], batch1["id"], 2000,
                     "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")

        # 120 ALLERGEN_CROSS + 30 fragrance carryover = 150 required.
        resp = api.create_run(order2["id"], {
            "line_id": line["id"], "batch_id": batch2["id"],
            "scheduled_start": "2026-05-10T12:29:00Z", "scheduled_end": "2026-05-10T13:30:00Z",
            "planned_units": 1000}, PP)
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_GAP_VIOLATION, 409)

        accepted = schedule_run(order2["id"], line["id"], batch2["id"], 1000,
                                "2026-05-10T12:30:00Z", "2026-05-10T13:30:00Z")
        assert_run(accepted)
        assert accepted["changeover_minutes_required"] == 150

    def test_same_formula_changeover_zero(self, api, production_planner_headers):
        """PRD §3.8: "The base requirement is zero minutes when both runs use the
        same formula".

        Design: Difficulty/resource_temporal_overlap/line_changeover_allergen_buffer
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=water["id"])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        batch1 = create_batch(order["id"], 50)
        batch2 = create_batch(order["id"], 50)
        line = create_line()
        schedule_run(order["id"], line["id"], batch1["id"], 1000,
                     "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")

        run2 = schedule_run(order["id"], line["id"], batch2["id"], 1000,
                            "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
        assert_run(run2)
        assert run2["changeover_minutes_required"] == 0


class TestRunStartGates:
    def test_run_start_requires_batch_released(self, api, production_planner_headers):
        """PRD §3.8: "Starting a run is a triple gate. The run must stand
        `SCHEDULED`; its referenced batch must stand `RELEASED_TO_FILLING`,
        failing with `ERR_BATCH_NOT_RELEASED` (HTTP 409); its line must stand
        `IDLE`, failing with `ERR_INVALID_STATE` (HTTP 409); and its order must
        stand `IN_PRODUCTION` or `FILLING`."

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_batch_released
        """
        ctx = mixing_batch_ctx()
        line = create_line()
        run = schedule_run(ctx["order"]["id"], line["id"], ctx["batch"]["id"], 2000,
                           "2026-05-10T08:00:00Z", "2026-05-10T10:00:00Z")

        # Batch is still MIXING.
        resp = api.start_run(run["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_RELEASED, 409)

        record_ipc_check(ctx["batch"]["id"], "VISCOSITY", 4000, QA1)
        record_ipc_check(ctx["batch"]["id"], "PH", 5.5, QA1)
        release_batch(ctx["batch"]["id"], QA2)

        started = start_run(run["id"])
        assert_run(started)
        assert started["status"] == "IN_PROGRESS"

    def test_run_double_start_rejected(self, api, production_planner_headers):
        """PRD §3.8: "The run must stand `SCHEDULED`".
        PRD §2.8: "then state-transition legality (`ERR_INVALID_STATE`, HTTP 409
        — a transition attempted from a state that does not declare it, or from
        any terminal state, is rejected)".

        Design: Difficulty/cross_entity_state_dependency/run_start_requires_batch_released
        """
        ctx = in_progress_run_ctx()
        resp = api.start_run(ctx["run"]["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestLineCleaningCycle:
    def test_filling_line_cyclic(self, api, production_planner_headers):
        """PRD §3.8: "the line begins `IDLE`, moves to `RUNNING` when a run
        starts on it — carrying that run's identifier as `current_run_id` — and
        moves to `CLEANING` when its in-progress run completes or is aborted,
        clearing `current_run_id`. Cleaning closes the cycle: the planner
        finishes cleaning explicitly, returning the line from `CLEANING` to
        `IDLE`."
        PRD §3.8: "its line must stand `IDLE`, failing with `ERR_INVALID_STATE`
        (HTTP 409)".

        Design: Difficulty/non_linear_state_machine/filling_line_cyclic
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=water["id"])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])

        batches = []
        for _ in range(2):
            batch = create_batch(order["id"], 50)
            lot = create_lot(water["id"], quantity_received=200)
            allocate_lots(order["id"], [allocation_item(lot["id"], 50, batch_id=batch["id"])])
            start_mixing(batch["id"])
            record_ipc_check(batch["id"], "VISCOSITY", 4000, QA1)
            record_ipc_check(batch["id"], "PH", 5.5, QA1)
            batches.append(release_batch(batch["id"], QA2))

        line = create_line()
        run1 = schedule_run(order["id"], line["id"], batches[0]["id"], 1000,
                            "2026-05-10T08:00:00Z", "2026-05-10T09:00:00Z")
        start_run(run1["id"])
        complete_run(run1["id"], 1000)

        line_mid = validate_success(api.get_line(line["id"], production_planner_headers), 200)
        assert_line(line_mid)
        assert line_mid["status"] == "CLEANING"

        run2 = schedule_run(order["id"], line["id"], batches[1]["id"], 1000,
                            "2026-05-10T09:00:00Z", "2026-05-10T10:00:00Z")
        resp = api.start_run(run2["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        cleaned = finish_cleaning(line["id"])
        assert cleaned["status"] == "IDLE"

        started = start_run(run2["id"])
        assert_run(started)
        assert started["status"] == "IN_PROGRESS"
        line_end = validate_success(api.get_line(line["id"], production_planner_headers), 200)
        assert line_end["status"] == "RUNNING"
        assert line_end["current_run_id"] == run2["id"]

    def test_abort_in_progress_run_sends_line_to_cleaning(self, api, production_planner_headers,
                                                          qa_manager_headers):
        """PRD §3.8: "Aborting an `IN_PROGRESS` run moves it to `ABORTED`, sends
        its line from `RUNNING` to `CLEANING`, and leaves its batch standing
        `RELEASED_TO_FILLING`, unconsumed and available to a future run."

        Design: Difficulty/non_linear_state_machine/filling_line_cyclic
        """
        ctx = in_progress_run_ctx()
        aborted = abort_run(ctx["run"]["id"])
        assert_run(aborted)
        assert aborted["status"] == "ABORTED"

        line = validate_success(api.get_line(ctx["line"]["id"], production_planner_headers), 200)
        assert line["status"] == "CLEANING"
        assert line["current_run_id"] is None

        batch = validate_success(api.get_batch(ctx["batch"]["id"], qa_manager_headers), 200)
        assert batch["status"] == "RELEASED_TO_FILLING"

    def test_line_finish_cleaning_from_idle_rejected(self, api, production_planner_headers):
        """PRD §3.8: "Cleaning closes the cycle: the planner finishes cleaning
        explicitly, returning the line from `CLEANING` to `IDLE`."
        PRD §2.9: "Every stateful resource moves only along the transitions
        declared for its lifecycle in §3; terminal states reject every further
        transition."

        Design: Corner/state_machines/line_finish_cleaning_from_idle_rejected
        """
        line = create_line()
        resp = api.finish_cleaning(line["id"], production_planner_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestRunCompletion:
    def test_overfill_rejected_on_run_complete(self, api, production_planner_headers):
        """PRD §3.8: "Over-delivery is forbidden: the order's already-recorded
        `filled_units` plus the run's newly reported good units must not exceed
        the order's current `requested_units` — the originally requested quantity
        less any `forfeited_units`, escalation having already subtracted
        forfeited volume from `requested_units` itself — failing with
        `ERR_OVER_DELIVERY` (HTTP 422)."

        Design: Corner/validations/overfill_rejected_on_run_complete
        """
        ctx = in_progress_run_ctx(requested_units=1000, planned_units=1000)
        resp = api.complete_run(ctx["run"]["id"], {"filled_units": 1001}, PP)
        validate_error(resp, ApiErrorId.ERR_OVER_DELIVERY, 422)

        fetched = validate_success(api.get_run(ctx["run"]["id"], production_planner_headers), 200)
        assert fetched["status"] == "IN_PROGRESS"

    def test_order_completion_waits_for_label_review(self, api, production_planner_headers):
        """PRD §3.4: "And when a completing run brings the order's `filled_units`
        to at least its `requested_units`, the order moves from `FILLING` to
        `COMPLETED` — provided the formula's latest `LABEL_ARTWORK`-scope review
        stands `APPROVED`; if that label review has not yet been approved, the
        order remains `FILLING` until the approval lands and completes it per
        §3.3."
        PRD §3.3: "approval of a `LABEL_ARTWORK`-scope review completes every
        `FILLING` production order of that formula whose recorded `filled_units`
        have already reached the order's `requested_units`".

        Design: Corner/state_machines/order_completion_waits_for_label_review
        """
        ctx = in_progress_run_ctx(requested_units=1000, planned_units=1000)
        complete_run(ctx["run"]["id"], 1000)

        mid = validate_success(api.get_order(ctx["order"]["id"], production_planner_headers), 200)
        assert_order(mid)
        assert mid["filled_units"] == 1000
        assert mid["status"] == "FILLING", "no approved label review yet — order must wait in FILLING"

        approve_label_artwork(ctx["formula"]["id"])

        end = validate_success(api.get_order(ctx["order"]["id"], production_planner_headers), 200)
        assert end["status"] == "COMPLETED"


class TestOrderCancellationCascade:
    def _setup_cancel_scenario(self):
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        cap = create_customer_supplied_component(customer["id"], name="Cap", kind="SECONDARY_PACK")
        formula = create_active_formula(
            customer["id"], component_id=water["id"],
            required_components=[{"component_id": cap["id"], "units_per_product": 1}])
        order = create_order(customer["id"], formula["id"], 2000)
        confirm_order(order["id"], customer["id"])
        cap_lot = create_lot(cap["id"], lot_code="C1", quantity_received=300)
        allocations = allocate_lots(order["id"], [allocation_item(cap_lot["id"], 300)])
        batch = create_batch(order["id"], 50)
        line = create_line()
        run = schedule_run(order["id"], line["id"], batch["id"], 1000,
                           "2026-05-10T08:00:00Z", "2026-05-10T09:00:00Z")
        shortfall = declare_shortfall(order["id"], cap["id"], 1000)
        return customer, order, cap_lot, allocations, run, shortfall

    def test_order_cancel_cascade_depth2(self, api, production_planner_headers):
        """PRD §3.5: "Cancelling releases the order's `RESERVED` allocations
        (each released lot's `quantity_reserved` falls and its
        `quantity_available` rises by the released amount), moves its `SCHEDULED`
        filling runs to `ABORTED`, voids its `OPEN` and `COMMITMENT_RECEIVED`
        shortfall cases to `CLOSED_VOID`, and — for orders that had passed
        confirmation — decreases the customer's `outstanding_balance_cents` by
        the order's `quote_total_cents`."

        Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
        """
        (customer, order, cap_lot, allocations, run, shortfall) = self._setup_cancel_scenario()

        cancelled = cancel_order(order["id"], customer["id"])
        assert_order(cancelled)
        assert cancelled["status"] == "CANCELLED"

        allocation = validate_success(api.get_allocation(allocations[0]["id"], production_planner_headers), 200)
        assert allocation["status"] == "RELEASED"
        lot = validate_success(api.get_lot(cap_lot["id"], production_planner_headers), 200)
        assert_lot(lot)
        assert lot["quantity_available"] == 300
        assert lot["quantity_reserved"] == 0

        fetched_run = validate_success(api.get_run(run["id"], production_planner_headers), 200)
        assert fetched_run["status"] == "ABORTED"
        fetched_shortfall = validate_success(api.get_shortfall(shortfall["id"], production_planner_headers), 200)
        assert_shortfall(fetched_shortfall)
        assert fetched_shortfall["status"] == "CLOSED_VOID"

    def test_cancel_confirmed_order_restores_credit(self, api, plant_director_headers):
        """PRD §3.5: "Cancelling releases the order's `RESERVED` allocations
        (each released lot's `quantity_reserved` falls and its
        `quantity_available` rises by the released amount), moves its `SCHEDULED`
        filling runs to `ABORTED`, voids its `OPEN` and `COMMITMENT_RECEIVED`
        shortfall cases to `CLOSED_VOID`, and — for orders that had passed
        confirmation — decreases the customer's `outstanding_balance_cents` by
        the order's `quote_total_cents`."

        Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
        """
        customer = create_customer()
        water = create_component(name="Water", standard_cost_per_kg_cents=1000)
        formula = create_active_formula(customer["id"], component_id=water["id"])
        order1 = create_order(customer["id"], formula["id"], 1000)
        confirm_order(order1["id"], customer["id"])
        order2 = create_order(customer["id"], formula["id"], 1500)
        confirm_order(order2["id"], customer["id"])

        cancel_order(order1["id"], customer["id"])
        end = validate_success(api.get_customer(customer["id"], plant_director_headers), 200)
        assert end["outstanding_balance_cents"] == order2["quote_total_cents"], (
            "cancelling order1 must subtract exactly its own quote, leaving order2's exposure")
