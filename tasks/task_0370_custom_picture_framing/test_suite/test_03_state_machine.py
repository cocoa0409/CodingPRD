"""Order/line/task state machines: parallel dimensions, the intake-quote revision
cycle, frame-line branching, invalid/guarded transitions, terminal lockdown,
preconditions, reorder cloning, and cancel-cascade release.

Translates queue A (Difficulty) non_linear_state_machine (both instances) and
queue B (Corner) state_machines instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_order, add_line, measure_line, quote, pay,
    setup_order_with_line, setup_quoted_order, setup_deposit_paid_order,
    setup_in_production_order, setup_picked_up_order,
)

DESIGNER = TEST_USERS["frame_designer_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine / framing_order_parallel_production_and_payment
# ===========================================================================
def test_parallel_production_and_payment_dimensions(api):
    """PRD §3.5: "An order's payment dimension, `payment_status`, runs independently
    of its production dimension".
    PRD §3.5: "A **deposit** payment advances `payment_status` from `DEPOSIT_DUE` to
    `DEPOSIT_PAID`. It is permitted only when the order's `production_status` is
    `QUOTED`".

    Design: Difficulty/non_linear_state_machine/framing_order_parallel_production_and_payment_dimensions
    """
    cust, quoted, line = setup_quoted_order(deposit_pct=0.30, measure_dims=(8, 10))
    assert quoted["production_status"] == "QUOTED"
    pay(quoted["id"], "DEPOSIT", 25.00)
    refreshed = get_success_data(api.get_order(quoted["id"], CLERK))
    # Production axis unchanged while payment axis advanced.
    assert refreshed["production_status"] == "QUOTED"
    assert refreshed["payment_status"] == "DEPOSIT_PAID"


def test_parallel_dimensions_deposit_does_not_advance_production(api):
    """PRD §3.5: "A new order is `UNBILLED`; quoting moves it to `DEPOSIT_DUE` as
    described above."
    PRD §3.6: "An order moves from `QUOTED` to `IN_PRODUCTION` only when its
    `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL` ... and when every non-voided
    frame line has `line_status` of `MEASURED`".

    Second test for the parallel-dimensions instance: a paid deposit leaves the order
    in QUOTED until an explicit start-production transition fires.

    Design: Difficulty/non_linear_state_machine/framing_order_parallel_production_and_payment_dimensions
    """
    cust, quoted, line = setup_deposit_paid_order(deposit_pct=0.30, measure_dims=(8, 10))
    refreshed = get_success_data(api.get_order(quoted["id"], CLERK))
    assert refreshed["payment_status"] == "DEPOSIT_PAID"
    assert refreshed["production_status"] == "QUOTED"
    # Production only advances on the explicit transition.
    started = get_success_data(api.start_production(quoted["id"], TECH))
    assert started["production_status"] == "IN_PRODUCTION"
    assert started["payment_status"] == "DEPOSIT_PAID"


# ===========================================================================
# Difficulty: non_linear_state_machine / frame_line_branching_and_order_intake_quote_cycle
# ===========================================================================
def test_frame_line_branching_and_intake_quote_cycle(api):
    """PRD §3.2: "The first is **measuring** a line, which advances it from `DRAFT`
    to `MEASURED`".
    PRD §3.2: "The second is **voiding** a line, which advances it from `DRAFT` to
    `VOID`".
    PRD §3.4: "A `FrameDesigner` may **reopen** a quoted order back to `INTAKE` for
    revision, which is allowed only while `payment_status` is `UNBILLED` or
    `DEPOSIT_DUE`".

    Design: Difficulty/non_linear_state_machine/frame_line_branching_and_order_intake_quote_cycle
    """
    cust = create_customer(email="fi@x.com", full_name="Fi Cyc")
    order = create_order(cust["id"])
    line_a = add_line(order["id"], order["version"], artwork_label="A",
                      nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    refreshed = get_success_data(api.get_order(order["id"], DESIGNER))
    line_b = add_line(order["id"], refreshed["version"], artwork_label="B",
                      nominal_width_in=9, nominal_height_in=12, molding_rate_per_ui=0.30)
    voided = get_success_data(api.void_frame_line(line_a["id"], DESIGNER))
    assert voided["line_status"] == "VOID"
    measured = measure_line(line_b["id"], 9, 12)
    assert measured["line_status"] == "MEASURED"
    quote(order["id"])
    reopened = get_success_data(api.reopen_intake(order["id"], DESIGNER))
    assert reopened["production_status"] == "INTAKE"


def test_reopen_intake_allows_requote_cycle(api):
    """PRD §3.4: "Reopening returns the order to the editable `INTAKE` state so that
    lines may again be added or measured, and increments the order's `version`. This
    intake-to-quote revision loop may repeat until a deposit is taken."

    Second test for the branching/cycle instance: after reopening, the order quotes
    again (QUOTED->INTAKE->QUOTED loop).

    Design: Difficulty/non_linear_state_machine/frame_line_branching_and_order_intake_quote_cycle
    """
    cust, quoted, line = setup_quoted_order(measure_dims=(8, 10))
    assert quoted["production_status"] == "QUOTED"
    reopened = get_success_data(api.reopen_intake(quoted["id"], DESIGNER))
    assert reopened["production_status"] == "INTAKE"
    requoted = get_success_data(api.quote_order(quoted["id"], DESIGNER))
    assert requoted["production_status"] == "QUOTED"


# ===========================================================================
# Corner: state_machines
# ===========================================================================
def test_quote_from_already_quoted_returns_invalid_state(api):
    """PRD §2.6: "sixth, the target resource's state being valid for the requested
    transition — a transition attempted from a state that does not allow it fails in
    the 409 state family, defaulting to `ERR_INVALID_STATE` when no more specific
    state error ... applies".
    PRD §3.4: "Quoting an order is the `FrameDesigner` action that advances
    `production_status` from `INTAKE` to `QUOTED`."

    Design: Corner/state_machines/quote_from_already_quoted_returns_invalid_state
    """
    cust, quoted, line = setup_quoted_order(measure_dims=(8, 10))
    resp = api.quote_order(quoted["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_cancel_from_picked_up_terminal_returns_invalid_state(api):
    """PRD §3.7: "Pickup is a terminal production state".
    PRD §2.6: "a transition attempted from a state that does not allow it fails in
    the 409 state family, defaulting to `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_from_picked_up_terminal_returns_invalid_state
    """
    cust, picked, line, bench, task = setup_picked_up_order()
    assert picked["production_status"] == "PICKED_UP"
    resp = api.cancel_order(picked["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_reopen_intake_blocked_after_deposit_paid(api):
    """PRD §3.4: "Once a deposit has been collected, reopening is rejected with
    `ERR_DEPOSIT_ALREADY_PAID`."

    Design: Corner/state_machines/reopen_intake_blocked_after_deposit_paid
    """
    cust, quoted, line = setup_deposit_paid_order(deposit_pct=0.30, measure_dims=(8, 10))
    resp = api.reopen_intake(quoted["id"], DESIGNER)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_ALREADY_PAID)


def test_start_production_blocked_when_deposit_not_paid(api):
    """PRD §3.6: "An order moves from `QUOTED` to `IN_PRODUCTION` only when its
    `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL` — a deposit (or full payment)
    must be in hand, or the start is rejected with `ERR_DEPOSIT_NOT_PAID`".

    Design: Corner/state_machines/start_production_blocked_when_deposit_not_paid
    """
    cust, quoted, line = setup_quoted_order(deposit_pct=0.30, measure_dims=(8, 10))
    resp = api.start_production(quoted["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_PAID)


def test_measure_blocked_once_order_in_production(api):
    """PRD §3.2: "Two further edits are available to the `FrameDesigner` while the
    owning order's `production_status` is `INTAKE` or `QUOTED`; attempting either while
    the order is in any other production state is rejected with `ERR_ORDER_NOT_EDITABLE`."

    Design: Corner/state_machines/measure_blocked_once_order_in_production
    """
    cust, order, line = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    resp = api.measure_frame_line(line["id"], {"measured_width_in": 8, "measured_height_in": 10}, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_EDITABLE)


def test_cancel_cascades_release_of_scheduled_tasks(api):
    """PRD §3.8: "Every production task for the order that is `SCHEDULED` or
    `COMPLETED` is moved to `RELEASED`, which frees its half-open interval on the
    workbench so the bench becomes available again."

    Design: Corner/state_machines/cancel_cascades_release_of_scheduled_tasks
    """
    cust, order, line = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    bench = get_success_data(api.create_workbench({"bench_name": "Asm Cd", "bench_type": "ASSEMBLY"}, TECH))
    task = get_success_data(api.create_task(
        {"order_id": order["id"], "workbench_id": bench["id"], "start_minute": 0, "end_minute": 30}, TECH))
    cancelled = get_success_data(api.cancel_order(order["id"], CLERK))
    assert cancelled["production_status"] == "CANCELLED"
    refreshed_task = get_success_data(api.get_task(task["id"], TECH))
    assert refreshed_task["task_status"] == "RELEASED"


def test_reorder_clones_picked_up_order_into_new_intake(api):
    """PRD §3.8: "The new order opens in `production_status` of `INTAKE` with its
    `reorder_of_order_id` set to the source order's id, and the source order's
    non-voided frame lines are copied as fresh `DRAFT` lines on the new order."

    Design: Corner/state_machines/reorder_clones_picked_up_order_into_new_intake
    """
    cust, picked, line, bench, task = setup_picked_up_order()
    new_order = validate_success(api.reorder(picked["id"], {}, DESIGNER), expected_status=201)
    assert new_order["production_status"] == "INTAKE"
    assert new_order["reorder_of_order_id"] == picked["id"]


def test_reorder_from_non_terminal_source_returns_not_picked_up(api):
    """PRD §3.8: "Reorder clones a source order that is in `PICKED_UP` state into a
    brand-new order; a source order in any other state is rejected with
    `ERR_NOT_PICKED_UP`."

    Design: Corner/state_machines/reorder_from_non_terminal_source_returns_not_picked_up
    """
    cust = create_customer()
    order = create_order(cust["id"])  # stays INTAKE
    resp = api.reorder(order["id"], {}, DESIGNER)
    validate_error(resp, ApiErrorId.ERR_NOT_PICKED_UP)
