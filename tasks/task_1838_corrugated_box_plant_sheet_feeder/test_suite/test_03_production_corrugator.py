"""Corrugator scheduling: run windows, overlap, trim optimization, shift
capacity conservation, and the shift-cancel cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_order_to_awaiting_converting,
    assert_money,
    assert_msf,
    assert_shift_minutes_invariant,
    attach_order,
    create_accepted_order,
    create_box_order_payload,
    create_corrugator_run,
    create_customer,
    create_draft_order,
    create_grade,
    create_grade_44bc,
    create_work_shift,
    schedule_order_on_run,
    setup_customer_and_grade,
    validate_error,
    validate_success,
    TEST_USERS,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


def test_adjacent_run_windows_allowed(api, production_planner_headers):
    """PRD 3.4: "the run must not overlap any other non-`CANCELLED` run on the
    same shift under a pairwise half-open overlap rule — a conflict exists when
    the new run's start is strictly before an existing run's end and that
    existing run's start is strictly before the new run's end, so two runs that
    merely abut (the new run's start exactly equals the existing run's end) are
    allowed. An overlap is rejected with `ERR_RUN_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/corrugator_run_half_open_pairwise_overlap_with_adjacency_allowed
    """
    grade = create_grade()
    shift = create_work_shift(machine_code="CORRUGATOR")
    run1 = create_corrugator_run(shift["id"], grade["id"], 480, 720)
    assert run1["status"] == "SCHEDULED"
    run2 = create_corrugator_run(shift["id"], grade["id"], 720, 900)
    assert run2["status"] == "SCHEDULED", (
        "adjacent run [720,900) after [480,720) must be accepted"
    )


def test_overlapping_run_window_rejected(api, production_planner_headers):
    """PRD 3.4: "the run must not overlap any other non-`CANCELLED` run on the
    same shift under a pairwise half-open overlap rule — a conflict exists when
    the new run's start is strictly before an existing run's end and that
    existing run's start is strictly before the new run's end, so two runs that
    merely abut (the new run's start exactly equals the existing run's end) are
    allowed. An overlap is rejected with `ERR_RUN_WINDOW_OVERLAP`."
    PRD 3.4: "cancelled runs and bookings contribute nothing, and the rollup
    recomputes on every run or booking create, start, complete, or cancel."

    Design: Difficulty/resource_temporal_overlap/corrugator_run_half_open_pairwise_overlap_with_adjacency_allowed
    """
    grade = create_grade()
    shift = create_work_shift(machine_code="CORRUGATOR")
    create_corrugator_run(shift["id"], grade["id"], 480, 720)
    create_corrugator_run(shift["id"], grade["id"], 720, 900)

    res = api.create_corrugator_run(
        {
            "work_shift_id": shift["id"],
            "board_grade_id": grade["id"],
            "start_minute": 700,
            "end_minute": 800,
            "web_width_in": 87.0,
        },
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_RUN_WINDOW_OVERLAP, expected_status=409)

    shift_after = validate_success(
        api.get_work_shift(shift["id"], production_planner_headers)
    )
    assert shift_after["scheduled_minutes"] == 420  # 240 + 180; rejected run adds 0
    assert_shift_minutes_invariant(shift_after)


def test_shift_minutes_invariant_holds_across_run_create(
    api, production_planner_headers
):
    """PRD 3.4: "The shift opens in `OPEN` status with `scheduled_minutes` 0;
    `capacity_minutes` is `end_minute` minus `start_minute`, and
    `available_minutes` is `capacity_minutes` minus `scheduled_minutes`. The
    shift's `scheduled_minutes` is the sum of window lengths (`end_minute`
    minus `start_minute`) over its corrugator runs in `SCHEDULED` or
    `COMPLETED` status plus its converting bookings in `QUEUED`, `RUNNING`, or
    `COMPLETED` status".

    Design: Difficulty/compensating_invariant/shift_minutes_conserved_across_run_schedule_and_cancel
    """
    grade = create_grade()
    shift = create_work_shift(machine_code="CORRUGATOR")
    assert shift["capacity_minutes"] == 480
    assert shift["scheduled_minutes"] == 0
    assert shift["available_minutes"] == 480
    assert_shift_minutes_invariant(shift)

    create_corrugator_run(shift["id"], grade["id"], 480, 720)
    after = validate_success(api.get_work_shift(shift["id"], production_planner_headers))
    assert after["capacity_minutes"] == 480
    assert after["scheduled_minutes"] == 240
    assert after["available_minutes"] == 240
    assert_shift_minutes_invariant(after)


def test_shift_minutes_invariant_restored_after_run_cancel(
    api, production_planner_headers
):
    """PRD 3.4: "Cancellation — directly by a `ProductionPlanner`, or via the
    shift-cancel cascade — requires the run `SCHEDULED`, flips it to
    `CANCELLED`, reverts every attached order in `SCHEDULED` back to `ACCEPTED`
    with its `corrugator_run_id` cleared, frees the run's minutes in the shift
    rollup, and increments the run's `version`."

    Design: Difficulty/compensating_invariant/shift_minutes_conserved_across_run_schedule_and_cancel
    """
    grade = create_grade()
    shift = create_work_shift(machine_code="CORRUGATOR")
    run = create_corrugator_run(shift["id"], grade["id"], 480, 720)
    cancelled = validate_success(
        api.cancel_corrugator_run(run["id"], production_planner_headers)
    )
    assert cancelled["status"] == "CANCELLED"

    after = validate_success(api.get_work_shift(shift["id"], production_planner_headers))
    assert after["capacity_minutes"] == 480
    assert after["scheduled_minutes"] == 0
    assert after["available_minutes"] == 480
    assert_shift_minutes_invariant(after)


def test_shift_cancel_cancels_scheduled_run(api, production_planner_headers):
    """PRD 3.4: "A `ProductionPlanner` may cancel an `OPEN` shift (otherwise
    `ERR_INVALID_STATE`). The cancellation flips every `SCHEDULED` run on the
    shift to `CANCELLED`, and every `QUEUED` or `RUNNING` converting booking on
    the shift to `CANCELLED`."

    Design: Difficulty/transitive_cascade/work_shift_cancel_two_hop_cascade_to_orders
    """
    customer, grade = setup_customer_and_grade()
    order, _quote = create_accepted_order(customer["id"], grade["id"])
    shift, run = schedule_order_on_run(order["id"], grade["id"], outs=3)

    cancelled = validate_success(
        api.cancel_work_shift(shift["id"], production_planner_headers)
    )
    assert cancelled["status"] == "CANCELLED"
    run_after = validate_success(
        api.get_corrugator_run(run["id"], production_planner_headers)
    )
    assert run_after["status"] == "CANCELLED"


def test_shift_cancel_reverts_attached_order_and_frees_minutes(
    api, production_planner_headers
):
    """PRD 3.4: "Each run cancellation in turn reverts its attached `SCHEDULED`
    orders to `ACCEPTED` with `corrugator_run_id` cleared; each booking
    cancellation reverts its booked order to `AWAITING_CONVERTING` — from
    `DIE_CUT_QUEUED`, `SLOTTED_QUEUED`, or `CONVERTING` as applicable. The
    shift's capacity rollup then recomputes, and the shift's `version`
    increments."

    Design: Difficulty/transitive_cascade/work_shift_cancel_two_hop_cascade_to_orders
    """
    customer, grade = setup_customer_and_grade()
    order, _quote = create_accepted_order(customer["id"], grade["id"])
    shift, run = schedule_order_on_run(order["id"], grade["id"], outs=3)

    validate_success(api.cancel_work_shift(shift["id"], production_planner_headers))

    order_after = validate_success(api.get_box_order(order["id"], production_planner_headers))
    assert order_after["status"] == "ACCEPTED"
    assert order_after["corrugator_run_id"] is None

    shift_after = validate_success(
        api.get_work_shift(shift["id"], production_planner_headers)
    )
    assert shift_after["scheduled_minutes"] == 0
    assert shift_after["available_minutes"] == 480
    assert shift_after["capacity_minutes"] == 480


def test_trim_waste_rollup_two_order_run(api, production_planner_headers):
    """PRD 3.4: "`consumed_width_in` is the sum of `outs` times
    `blank_width_in` over all orders currently attached to the run; the
    summation is order-insensitive. `trim_waste_in` is `web_width_in` minus
    `consumed_width_in`, and `trim_waste_pct` is one hundred times
    `trim_waste_in` divided by `web_width_in`, rounded half-up to 2 decimal
    places. These recompute on every attach, on an order-cancel detach, and on
    run cancel. Notably, the acceptability of the waste is judged at run
    completion, not per attach, so a multi-order run can be built up
    incrementally".

    Design: Corner/calculations/trim_waste_pct_correct_result_two_order_run
    """
    customer, grade = setup_customer_and_grade()
    order_a, _ = create_accepted_order(
        customer["id"], grade["id"], ink_colors=[]
    )  # 29 in blank
    order_b, _ = create_accepted_order(
        customer["id"],
        grade["id"],
        unit_price=50.00,
        routing_type="SLOTTED",
        quantity=1000,
        blank_width_in=24.0,
        blank_length_in=20.0,
        min_ect_required=30,
        ink_colors=[],
    )

    shift = create_work_shift(machine_code="CORRUGATOR")
    run = create_corrugator_run(shift["id"], grade["id"], 480, 720)

    after_a = attach_order(run["id"], order_a["id"], 2)
    assert_msf(after_a["consumed_width_in"], 58.0)
    assert_msf(after_a["trim_waste_in"], 29.0)  # waste gate not judged at attach

    after_b = attach_order(run["id"], order_b["id"], 1)
    assert_msf(after_b["consumed_width_in"], 82.0)
    assert_msf(after_b["trim_waste_in"], 5.0)
    assert_money(after_b["trim_waste_pct"], 5.75)  # round2(100 * 5 / 87)

    for order in (order_a, order_b):
        read_back = validate_success(
            api.get_box_order(order["id"], production_planner_headers)
        )
        assert read_back["status"] == "SCHEDULED"
        assert read_back["corrugator_run_id"] == run["id"]


def test_trim_waste_gate_at_complete_and_width_gate_at_attach(
    api, production_planner_headers
):
    """PRD 3.4: "the trim fit must hold — the run's `consumed_width_in` plus
    `outs` times the order's `blank_width_in` must not exceed the run's
    `web_width_in`, with an exact fit allowed (otherwise
    `ERR_TRIM_WIDTH_EXCEEDS_WEB`)".
    PRD 3.4: "completing a run requires `trim_waste_in` to be at most 8.0
    inches, with exactly 8.0 allowed, and an excess rejects the completion with
    `ERR_TRIM_WASTE_EXCESSIVE` while the run stays `SCHEDULED`."

    Design: Corner/validations/trim_gates_excessive_at_complete_and_exceeds_web_at_attach
    """
    customer, grade = setup_customer_and_grade()
    order_c, _ = create_accepted_order(
        customer["id"], grade["id"], unit_price=50.00, routing_type="SLOTTED",
        quantity=500, blank_width_in=30.0, blank_length_in=20.0,
        min_ect_required=30, ink_colors=[],
    )
    order_a, _ = create_accepted_order(
        customer["id"], grade["id"], unit_price=50.00, routing_type="SLOTTED",
        quantity=2000, blank_width_in=29.0, blank_length_in=36.0,
        min_ect_required=30, ink_colors=[],
    )
    order_b, _ = create_accepted_order(
        customer["id"], grade["id"], unit_price=50.00, routing_type="SLOTTED",
        quantity=1000, blank_width_in=24.0, blank_length_in=20.0,
        min_ect_required=30, ink_colors=[],
    )
    order_d, _ = create_accepted_order(
        customer["id"], grade["id"], unit_price=50.00, routing_type="SLOTTED",
        quantity=100, blank_width_in=6.0, blank_length_in=10.0,
        min_ect_required=30, ink_colors=[],
    )

    shift = create_work_shift(machine_code="CORRUGATOR")
    run1 = create_corrugator_run(shift["id"], grade["id"], 480, 600)
    attach_order(run1["id"], order_c["id"], 2)  # consumed 60, waste 27
    run2 = create_corrugator_run(shift["id"], grade["id"], 600, 900)
    attach_order(run2["id"], order_a["id"], 2)  # 58
    attach_order(run2["id"], order_b["id"], 1)  # 82

    # Completion gate: waste 27 > 8.0 -> rejected, run stays SCHEDULED
    res = api.complete_corrugator_run(run1["id"], production_planner_headers)
    validate_error(res, ApiErrorId.ERR_TRIM_WASTE_EXCESSIVE, expected_status=422)
    run1_after = validate_success(
        api.get_corrugator_run(run1["id"], production_planner_headers)
    )
    assert run1_after["status"] == "SCHEDULED"
    order_c_after = validate_success(
        api.get_box_order(order_c["id"], production_planner_headers)
    )
    assert order_c_after["status"] == "SCHEDULED"

    # Attach gate: 82 + 6 = 88 > 87 web -> rejected, consumed unchanged
    res2 = api.attach_order_to_run(
        run2["id"], {"box_order_id": order_d["id"], "outs": 1},
        production_planner_headers,
    )
    validate_error(res2, ApiErrorId.ERR_TRIM_WIDTH_EXCEEDS_WEB, expected_status=422)
    run2_after = validate_success(
        api.get_corrugator_run(run2["id"], production_planner_headers)
    )
    assert_msf(run2_after["consumed_width_in"], 82.0)


def test_run_window_outside_shift_rejected(api, production_planner_headers):
    """PRD 3.4: "the run window must lie inside the shift window with both
    endpoints inclusive — `start_minute` no earlier than the shift's
    `start_minute` and `end_minute` no later than the shift's `end_minute`
    (otherwise `ERR_OUTSIDE_SHIFT_WINDOW`)".

    Design: Corner/validations/run_outside_shift_window_rejected
    """
    grade = create_grade()
    shift = create_work_shift(machine_code="CORRUGATOR")  # [480, 960)

    outside = api.create_corrugator_run(
        {
            "work_shift_id": shift["id"],
            "board_grade_id": grade["id"],
            "start_minute": 950,
            "end_minute": 1000,
            "web_width_in": 87.0,
        },
        production_planner_headers,
    )
    validate_error(outside, ApiErrorId.ERR_OUTSIDE_SHIFT_WINDOW, expected_status=422)

    inside = api.create_corrugator_run(
        {
            "work_shift_id": shift["id"],
            "board_grade_id": grade["id"],
            "start_minute": 780,
            "end_minute": 960,
            "web_width_in": 87.0,
        },
        production_planner_headers,
    )
    run = validate_success(inside, 201)
    assert run["status"] == "SCHEDULED"  # end exactly at shift end is inside


def test_attach_order_grade_mismatch_rejected(api, production_planner_headers):
    """PRD 3.4: "the order's `board_grade_id` must equal the run's
    `board_grade_id` (otherwise `ERR_ORDER_GRADE_MISMATCH`)".

    Design: Corner/errors/attach_order_grade_mismatch_rejected
    """
    customer = create_customer()
    grade_32 = create_grade()
    grade_44 = create_grade_44bc()
    order, _ = create_accepted_order(
        customer["id"], grade_32["id"], unit_price=50.00, routing_type="SLOTTED",
        quantity=100, blank_width_in=24.0, blank_length_in=20.0,
        min_ect_required=30, ink_colors=[],
    )
    shift = create_work_shift(machine_code="CORRUGATOR")
    run = create_corrugator_run(shift["id"], grade_44["id"], 480, 720)

    res = api.attach_order_to_run(
        run["id"], {"box_order_id": order["id"], "outs": 1},
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_ORDER_GRADE_MISMATCH, expected_status=422)

    order_after = validate_success(
        api.get_box_order(order["id"], production_planner_headers)
    )
    assert order_after["status"] == "ACCEPTED"
    assert order_after["corrugator_run_id"] is None
    run_after = validate_success(
        api.get_corrugator_run(run["id"], production_planner_headers)
    )
    assert_msf(run_after["consumed_width_in"], 0.0)


def test_attach_draft_order_state_error_precedes_grade_mismatch(
    api, production_planner_headers
):
    """PRD 2.7: "When a request trips multiple rules, the first applicable rule
    by the following priority order determines the error." ... "State-machine
    legality follows (priority 4) — wrong-state transitions
    (`ERR_INVALID_STATE`)"; order-grade equality is among the sixth-priority
    business constraints.
    PRD 3.4: "the order must be `ACCEPTED` (otherwise `ERR_INVALID_STATE`)".

    Design: Corner/validations/attach_draft_order_state_beats_grade_constraint
    """
    customer = create_customer()
    grade_32 = create_grade()
    grade_44 = create_grade_44bc()
    order = create_draft_order(
        customer["id"], grade_32["id"], routing_type="SLOTTED", quantity=100,
        blank_width_in=24.0, blank_length_in=20.0, min_ect_required=30,
        ink_colors=[],
    )
    shift = create_work_shift(machine_code="CORRUGATOR")
    run = create_corrugator_run(shift["id"], grade_44["id"], 480, 720)

    res = api.attach_order_to_run(
        run["id"], {"box_order_id": order["id"], "outs": 1},
        production_planner_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    run_after = validate_success(
        api.get_corrugator_run(run["id"], production_planner_headers)
    )
    assert_msf(run_after["consumed_width_in"], 0.0)


def test_board_source_mismatch_both_directions(api, production_planner_headers):
    """PRD 3.5: "when the feeder delivers, a `ProductionPlanner` marks sheets
    received on an `ACCEPTED` order whose `board_source` is `SHEET_FEEDER` (an
    `INTERNAL` order on this operation is rejected with
    `ERR_BOARD_SOURCE_MISMATCH`; a non-`ACCEPTED` order with
    `ERR_INVALID_STATE`)".
    PRD 3.4: "the order's `board_source` must be `INTERNAL` — a `SHEET_FEEDER`
    order on this operation is rejected with `ERR_BOARD_SOURCE_MISMATCH`".

    Design: Corner/validations/board_source_mismatch_both_directions
    """
    customer, grade = setup_customer_and_grade()
    order_i, _ = create_accepted_order(
        customer["id"], grade["id"], unit_price=50.00, routing_type="SLOTTED",
        quantity=100, blank_width_in=24.0, blank_length_in=20.0,
        min_ect_required=30, ink_colors=[],
    )
    order_s, _ = create_accepted_order(
        customer["id"], grade["id"], unit_price=50.00, routing_type="SLOTTED",
        board_source="SHEET_FEEDER", sheet_supplier_name="SheetCo",
        quantity=100, blank_width_in=24.0, blank_length_in=20.0,
        min_ect_required=30, ink_colors=[],
    )
    shift = create_work_shift(machine_code="CORRUGATOR")
    run = create_corrugator_run(shift["id"], grade["id"], 480, 720)

    res = api.mark_sheets_received(order_i["id"], production_planner_headers)
    validate_error(res, ApiErrorId.ERR_BOARD_SOURCE_MISMATCH, expected_status=422)
    order_i_after = validate_success(
        api.get_box_order(order_i["id"], production_planner_headers)
    )
    assert order_i_after["status"] == "ACCEPTED"

    res2 = api.attach_order_to_run(
        run["id"], {"box_order_id": order_s["id"], "outs": 1},
        production_planner_headers,
    )
    validate_error(res2, ApiErrorId.ERR_BOARD_SOURCE_MISMATCH, expected_status=422)
    order_s_after = validate_success(
        api.get_box_order(order_s["id"], production_planner_headers)
    )
    assert order_s_after["status"] == "ACCEPTED"
    run_after = validate_success(
        api.get_corrugator_run(run["id"], production_planner_headers)
    )
    assert_msf(run_after["consumed_width_in"], 0.0)
