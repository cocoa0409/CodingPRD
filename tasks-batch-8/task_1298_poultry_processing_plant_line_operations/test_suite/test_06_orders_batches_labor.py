"""Customer orders, deboning batches, the labor ledger, order cancellation,
and pagination over list endpoints."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_labor_invariant,
    create_flock_lot_payload, receive_flock_lot_payload, create_order_payload,
    create_deboning_batch_payload, create_line_run_payload,
    make_line, make_shift, book_and_receive_lot, make_order, make_batch,
    complete_batch, setup_chilled_lot, setup_production_line_for_deboning,
    setup_running_shift_with_run,
    queue_run, set_clock,
    TEST_USERS,
)

PM = TEST_USERS["plant_manager_headers"]
SUP = TEST_USERS["shift_supervisor_headers"]
RCV = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["line_operator_headers"]
QA = TEST_USERS["qa_technician_headers"]
PLAN = TEST_USERS["order_planner_headers"]


class TestLaborLedger:

    def test_labor_hours_conserved_on_batch_create_cancel(self, api):
        """PRD §3.6: "The estimate, `estimated_labor_hours`, is the
        `input_weight_lb` divided by 500 — one budgeted labor hour per five
        hundred pounds of input — rounded half-up to two decimal places, and it
        is debited from the shift at creation."
        PRD §3.6: "The ledger is conservative in both directions: creating and
        then cancelling the same `SCHEDULED` batch leaves
        `labor_hours_remaining` exactly unchanged."

        Design: Difficulty/compensating_invariant/labor_hours_conserved_on_batch_create_cancel
        """
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        shift = make_shift(labor_hours_budget=10.0)
        lot = book_and_receive_lot(shift["id"])
        order = make_order(pounds_ordered=1500.0, temperature_requirement="FROZEN",
                           product_code="THIGH_MEAT", customer_name="CustL")

        batch = validate_success(api.create_deboning_batch(
            create_deboning_batch_payload(order["id"], lot["id"], shift["id"],
                                          db_line["id"], crew_count=8,
                                          input_weight_lb=2000.0), SUP),
            expected_status=201)
        # round_half_up(2000/500, 2) == 4.0
        assert batch["estimated_labor_hours"] == pytest.approx(4.0)
        after_create = get_success_data(api.get_shift(shift["id"], SUP))
        assert after_create["labor_hours_remaining"] == pytest.approx(6.0)

        validate_success(api.advance_deboning_batch(batch["id"], {"to_status": "CANCELLED"}, OP))
        after_cancel = get_success_data(api.get_shift(shift["id"], SUP))
        assert after_cancel["labor_hours_remaining"] == pytest.approx(10.0)
        assert_labor_invariant(after_cancel)

    def test_labor_estimate_rounding_precision(self, api):
        """PRD §3.6: "The estimate, `estimated_labor_hours`, is the
        `input_weight_lb` divided by 500 — one budgeted labor hour per five
        hundred pounds of input — rounded half-up to two decimal places".
        PRD §2.9: "All computed decimal quantities the API reports — water
        intensity rates, flock yields, labor-hour estimates, remaining labor,
        and deboned net weights — are rounded half-up to exactly 2 decimal
        places."

        Design: Corner/calculations/labor_estimate_rounding_precision
        """
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        shift = make_shift(labor_hours_budget=50.0)
        lot = book_and_receive_lot(shift["id"])
        order = make_order(pounds_ordered=300.0, temperature_requirement="FROZEN",
                           product_code="TENDERLOIN", customer_name="CustP")
        batch = validate_success(api.create_deboning_batch(
            create_deboning_batch_payload(order["id"], lot["id"], shift["id"],
                                          db_line["id"], crew_count=4,
                                          input_weight_lb=333.0), SUP),
            expected_status=201)
        # round_half_up(333/500, 2) == round_half_up(0.666, 2) == 0.67
        assert batch["estimated_labor_hours"] == pytest.approx(0.67)

    def test_batch_create_window_closed_and_labor_exceeded_temporal_wins(self, api):
        """PRD §2.6: "Time-window rules (priority 7). Rules evaluated against
        the logical clock — batch creation after an order's due time
        (`ERR_ORDER_WINDOW_CLOSED`)…".
        PRD §2.6: "Fiscal gate (priority 9). The deboning labor budget check,
        `ERR_LABOR_BUDGET_EXCEEDED` (HTTP 402), runs last, after every other
        validation on batch creation has passed."
        PRD §3.6: "Two forward gates apply at creation: the order's `due_at`
        must still lie in the future of the logical clock, else
        `ERR_ORDER_WINDOW_CLOSED`, and the batch's estimated labor must fit the
        shift's remaining budget, else `ERR_LABOR_BUDGET_EXCEEDED` — this
        fiscal check runs last, after every other validation, per the ladder of
        §2.6."

        Design: Difficulty/priority_pair_validation_conflict/batch_create_window_closed_and_labor_exceeded_temporal_wins
        """
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        shift = make_shift(labor_hours_budget=1.0)  # est 2.0 for 1000 lb > 1.0 remaining
        lot = book_and_receive_lot(shift["id"])
        order = make_order(pounds_ordered=100.0, temperature_requirement="FROZEN",
                           product_code="THIGH_MEAT", customer_name="CustZ",
                           due_at="2026-08-01T06:00:00Z")
        set_clock("2026-08-01T12:00:00Z")  # due_at already passed
        resp = api.create_deboning_batch(
            create_deboning_batch_payload(order["id"], lot["id"], shift["id"],
                                          db_line["id"], crew_count=4,
                                          input_weight_lb=1000.0), SUP)
        # Both violations hold; the temporal rung fires before the fiscal rung
        validate_error(resp, ApiErrorId.ERR_ORDER_WINDOW_CLOSED)


class TestBatchLifecycle:

    def test_batch_on_evisceration_line_rejected(self, api):
        """PRD §3.6: "A `ShiftSupervisor` schedules a deboning batch against an
        order by naming the `order_id`, the source `flock_lot_id`, the
        `shift_id` whose labor budget will be debited, the `line_id` — which
        must be a `DEBONING` line, else `ERR_LINE_TYPE_MISMATCH`".

        Design: Corner/validations/batch_on_evisceration_line_rejected
        """
        ev_line = make_line()
        shift = make_shift()
        lot = book_and_receive_lot(shift["id"])
        order = make_order()
        resp = api.create_deboning_batch(
            create_deboning_batch_payload(order["id"], lot["id"], shift["id"],
                                          ev_line["id"], crew_count=6,
                                          input_weight_lb=500.0), SUP)
        validate_error(resp, ApiErrorId.ERR_LINE_TYPE_MISMATCH)

    def test_batch_complete_from_scheduled_rejected(self, api):
        """PRD §3.6: "Completing a batch — `IN_PROGRESS` → `COMPLETED` —
        requires the operator to supply `actual_output_weight_lb` and
        `actual_labor_hours`, each greater than zero (else
        `ERR_INVALID_REQUEST`); completion attempted from any other state is
        rejected with `ERR_BATCH_NOT_ADVANCEABLE`."

        Design: Corner/validations/batch_complete_from_scheduled_rejected
        """
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        shift = make_shift()
        lot = book_and_receive_lot(shift["id"])
        order = make_order()
        batch = make_batch(order["id"], lot["id"], shift["id"], db_line["id"],
                           crew_count=6, input_weight_lb=500.0)
        resp = api.advance_deboning_batch(
            batch["id"], {"to_status": "COMPLETED", "actual_output_weight_lb": 480.0,
                          "actual_labor_hours": 1.0}, OP)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_ADVANCEABLE)
        after = get_success_data(api.get_deboning_batch(batch["id"], OP))
        assert after["status"] == "SCHEDULED"

    def test_deboning_batch_start_requires_lot_chilled(self, api):
        """PRD §3.6: "Starting — `SCHEDULED` → `IN_PROGRESS` — requires the
        enclosing shift in `RUNNING` (else `ERR_SHIFT_NOT_RUNNING`) and the
        source lot at `CHILLED`, `SETTLED`, or `REOPENED` (else
        `ERR_LOT_NOT_CHILLED`)".

        Design: Difficulty/cross_entity_state_dependency/deboning_batch_start_requires_lot_chilled
        """
        env = setup_running_shift_with_run()  # run QUEUED->RUNNING... lot only RECEIVED
        # Do not run the lot's run to completion: the lot stays RECEIVED.
        # Reuse a fresh lot never put on the line:
        lot = book_and_receive_lot(env["shift"]["id"], lot_code="FL-200",
                                   grower_name="GrowerB")
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        order = make_order()
        batch = make_batch(order["id"], lot["id"], env["shift"]["id"], db_line["id"])
        resp = api.advance_deboning_batch(batch["id"], {"to_status": "IN_PROGRESS"}, OP)
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_CHILLED)
        after = get_success_data(api.get_deboning_batch(batch["id"], OP))
        assert after["status"] == "SCHEDULED"

    def test_order_fill_round_per_batch_then_sum(self, api):
        """PRD §2.9: "The rounding order is pinned where it matters: each
        deboning batch's net weight is rounded first, and only then are
        per-batch values summed into an order's filled quantity; summing raw
        outputs and rounding once at the end is the rejected alternative and
        yields different cents."
        PRD §3.6: "Allocation follows directly: `filled_lb` of exactly zero
        leaves the order `UNALLOCATED`; greater than zero but less than
        `pounds_ordered` makes it `PARTIALLY_ALLOCATED`; and `filled_lb`
        greater than or equal to `pounds_ordered` — equality allocates — makes
        it `ALLOCATED`."

        Design: Difficulty/combinatorial_formula/order_fill_round_per_batch_then_sum
        """
        env = setup_production_line_for_deboning(
            order_pounds=29.41, temperature_requirement="FROZEN",
            product_code="TENDERLOIN", customer_name="CustR",
            input_weight_lb=100.0, crew_count=6, due_at="2026-08-03T00:00:00Z")
        b1 = env["batch"]
        b1 = complete_batch(b1["id"], actual_output_weight_lb=10.005, actual_labor_hours=0.5)
        # round_half_up(10.005 * 0.98, 2) == round_half_up(9.8049, 2) == 9.80
        assert b1["net_weight_lb"] == pytest.approx(9.80)

        b2 = make_batch(env["order"]["id"], env["lot"]["id"], env["shift"]["id"],
                        env["deboning_line"]["id"], crew_count=6, input_weight_lb=100.0)
        b2 = complete_batch(b2["id"], actual_output_weight_lb=20.005, actual_labor_hours=0.5)
        # round_half_up(20.005 * 0.98, 2) == round_half_up(19.6049, 2) == 19.60
        assert b2["net_weight_lb"] == pytest.approx(19.60)

        order = get_success_data(api.get_order(env["order"]["id"], PLAN))
        # Per-batch sum: 9.80 + 19.60 = 29.40 (sum-then-round would give 29.41)
        assert order["filled_lb"] == pytest.approx(29.40)
        assert order["allocation_status"] == "PARTIALLY_ALLOCATED"


class TestOrderLifecycle:

    def test_order_parallel_allocation_fulfillment_dimensions(self, api):
        """PRD §3.6: "The order carries two parallel status dimensions that
        evolve independently on the same row: `fulfillment_status`, which runs
        `PENDING` → `IN_PRODUCTION` → `FULFILLED` with `CANCELLED` reachable
        from either of the first two, and `allocation_status`, which runs
        `UNALLOCATED` → `PARTIALLY_ALLOCATED` → `ALLOCATED`, driven purely by
        how the order's `filled_lb` compares with its `pounds_ordered`."
        PRD §3.7: "each ship re-evaluates the order's fulfillment, moving the
        order from `IN_PRODUCTION` to `FULFILLED` when the sum of
        `net_weight_lb` over the order's `SHIPPED` finished lots reaches or
        exceeds its `pounds_ordered`."

        Design: Difficulty/non_linear_state_machine/order_parallel_allocation_fulfillment_dimensions
        """
        env = setup_production_line_for_deboning(
            order_pounds=500.0, temperature_requirement="FLEXIBLE",
            input_weight_lb=1000.0, crew_count=12)
        oid, bid = env["order"]["id"], env["batch"]["id"]

        # Start batch: fulfillment IN_PRODUCTION, allocation still UNALLOCATED
        get_success_data(api.advance_deboning_batch(bid, {"to_status": "IN_PROGRESS"}, OP))
        mid = get_success_data(api.get_order(oid, PLAN))
        assert mid["fulfillment_status"] == "IN_PRODUCTION"
        assert mid["allocation_status"] == "UNALLOCATED"

        # Complete batch: 980 lb output -> net 960.40 >= 500 -> ALLOCATED
        get_success_data(api.advance_deboning_batch(
            bid, {"to_status": "COMPLETED", "actual_output_weight_lb": 980.0,
                  "actual_labor_hours": 2.0}, OP))
        done = get_success_data(api.get_order(oid, PLAN))
        assert done["fulfillment_status"] == "IN_PRODUCTION"
        assert done["allocation_status"] == "ALLOCATED"
        assert done["filled_lb"] == pytest.approx(960.40)

        # Ship the whole net: fulfillment FULFILLED
        lots, _ = validate_paginated(api.list_finished_lots(QA))
        fl = lots[0]
        get_success_data(api.trace_lock_finished_lot(fl["id"], {}, QA))
        get_success_data(api.advance_finished_lot(fl["id"], {"to_status": "SHIPPED"}, SUP))
        shipped = get_success_data(api.get_order(oid, PLAN))
        assert shipped["fulfillment_status"] == "FULFILLED"

    def test_order_cancel_cascades_to_scheduled_batches(self, api):
        """PRD §3.6: "Cancellation — from `PENDING` or `IN_PRODUCTION` to
        `CANCELLED` — is permitted only when no batch of the order is in
        `IN_PROGRESS` or `ON_HOLD`, else `ERR_ORDER_NOT_CANCELLABLE`; on
        cancel, every `SCHEDULED` batch of the order cascades to `CANCELLED`,
        releasing its estimated labor back to the shift."

        Design: Corner/state_machines/order_cancel_cascades_to_scheduled_batches
        """
        db_line = make_line(line_code="DB-1", line_type="DEBONING", rated_speed_bpm=50)
        shift = make_shift(labor_hours_budget=50.0)
        lot = book_and_receive_lot(shift["id"])
        order = make_order(pounds_ordered=2000.0, temperature_requirement="FROZEN",
                           product_code="THIGH_MEAT", customer_name="CustC")
        b1 = make_batch(order["id"], lot["id"], shift["id"], db_line["id"],
                        crew_count=8, input_weight_lb=2000.0)
        b2 = make_batch(order["id"], lot["id"], shift["id"], db_line["id"],
                        crew_count=8, input_weight_lb=1000.0)
        before = get_success_data(api.get_shift(shift["id"], SUP))
        assert before["labor_hours_remaining"] == pytest.approx(44.0)  # 50 - 4.0 - 2.0

        cancelled = validate_success(api.cancel_order(order["id"], {}, PLAN))
        assert cancelled["fulfillment_status"] == "CANCELLED"

        batches, _ = validate_paginated(api.list_deboning_batches(
            SUP, params={"order_id": order["id"]}))
        statuses = {b["id"]: b["status"] for b in batches}
        assert statuses[b1["id"]] == "CANCELLED"
        assert statuses[b2["id"]] == "CANCELLED"

        after = get_success_data(api.get_shift(shift["id"], SUP))
        assert after["labor_hours_remaining"] == pytest.approx(50.0)

    def test_order_amend_after_production_started_rejected(self, api):
        """PRD §3.6: "While `fulfillment_status` remains `PENDING`, the planner
        may amend the order — any of `pounds_ordered`, `due_at`, or
        `temperature_requirement` — through the second of the plant's
        optimistic-concurrency writes, carrying `expected_order_version`; a
        version mismatch is `ERR_STALE_ORDER_VERSION`, and a successful
        amendment increments the order's `version` by one. Once fulfillment has
        left `PENDING`, amendment is rejected with `ERR_ORDER_NOT_AMENDABLE`."

        Design: Corner/validations/order_amend_after_production_started_rejected
        """
        env = setup_production_line_for_deboning()
        get_success_data(api.advance_deboning_batch(
            env["batch"]["id"], {"to_status": "IN_PROGRESS"}, OP))
        fresh = get_success_data(api.get_order(env["order"]["id"], PLAN))
        assert fresh["fulfillment_status"] == "IN_PRODUCTION"
        resp = api.amend_order(env["order"]["id"],
                               {"pounds_ordered": 600.0,
                                "expected_order_version": fresh["version"]}, PLAN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_AMENDABLE)

    def test_order_cancel_with_in_progress_batch_rejected(self, api):
        """PRD §3.6: "Cancellation — from `PENDING` or `IN_PRODUCTION` to
        `CANCELLED` — is permitted only when no batch of the order is in
        `IN_PROGRESS` or `ON_HOLD`, else `ERR_ORDER_NOT_CANCELLABLE`".

        Design: Corner/validations/order_cancel_with_in_progress_batch_rejected
        """
        env = setup_production_line_for_deboning()
        get_success_data(api.advance_deboning_batch(
            env["batch"]["id"], {"to_status": "IN_PROGRESS"}, OP))
        resp = api.cancel_order(env["order"]["id"], {}, PLAN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        order = get_success_data(api.get_order(env["order"]["id"], PLAN))
        assert order["fulfillment_status"] == "IN_PRODUCTION"
        batch = get_success_data(api.get_deboning_batch(env["batch"]["id"], OP))
        assert batch["status"] == "IN_PROGRESS"


class TestLineRunListing:

    def test_pagination_limit_offset_interaction(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted, accepts a minimum of 1, and
        is capped at a maximum of 100. The `offset` parameter sets how many
        items to skip and defaults to 0."
        PRD §3.4: "Runs may be listed with optional filters `shift_id`,
        `line_id`, and `flock_lot_id`, with standard pagination."

        Design: Corner/complexity_layers/pagination_limit_offset_interaction
        """
        line = make_line()
        shift = make_shift(shackle_capacity_birds=30000)
        lot_a = get_success_data(api.create_flock_lot(
            create_flock_lot_payload(shift["id"], lot_code="FL-A",
                                     booked_head_count=9000), RCV))
        lot_b = get_success_data(api.create_flock_lot(
            create_flock_lot_payload(shift["id"], lot_code="FL-B",
                                     grower_name="GrowerB", booked_head_count=9000), RCV))
        ra = queue_run(shift["id"], line["id"], lot_a["id"], planned_speed_bpm=170)
        queue_run(shift["id"], line["id"], lot_a["id"], planned_speed_bpm=170)
        rc = queue_run(shift["id"], line["id"], lot_b["id"], planned_speed_bpm=170)

        page1, meta1 = validate_paginated(api.list_line_runs(
            OP, params={"shift_id": shift["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_line_runs(
            OP, params={"shift_id": shift["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        filtered, meta3 = validate_paginated(api.list_line_runs(
            OP, params={"flock_lot_id": lot_b["id"]}))
        assert len(filtered) == 1
        assert filtered[0]["id"] == rc["id"]
