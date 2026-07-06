"""Production-run availability cycle, par reserve/release cascades, swap conservation, run-cancel
compensation, and the kitchen-line buffer.

Translates non-linear (cyclic), transitive-cascade, compensating-invariant, and
resource-temporal-overlap difficulty instances (queue A) plus corner cascade/state instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, make_admin_headers, make_customer_headers,
    assert_par_conserved,
    create_production_run_payload, create_box_item_payload, swap_box_item_payload,
    setup_run5_box_open, setup_run5_box_selected5, setup_two_runs_box_item3,
    setup_open_run_box_selected3, setup_run_on_line_l1,
    seed_meal, seed_run,
)

ADMIN = make_admin_headers()


def test_reserving_last_serving_flips_run_sold_out(api):
    """PRD §2.8: "When a reservation drives `par_remaining` to exactly zero the run flips from
    `AVAILABLE` to `SOLD_OUT`; when a release raises `par_remaining` back above zero a `SOLD_OUT`
    run returns to `AVAILABLE`, closing the availability cycle."

    Design: Difficulty/non_linear_state_machine/production_run_cyclic_sold_out_to_available
    """
    ctx = setup_run5_box_open(api)  # par_total 5, box OPEN
    validate_success(api.create_box_item(
        ctx["box_id"], create_box_item_payload(ctx["m1_id"], 5),
        make_customer_headers(ctx["cust_id"])), 201)
    run = validate_success(api.get_production_run(ctx["run_id"], ADMIN), 200)
    assert run["status"] == "SOLD_OUT"
    assert run["par_remaining"] == 0


def test_releasing_servings_returns_run_to_available(api):
    """PRD §2.8: "when a release raises `par_remaining` back above zero a `SOLD_OUT` run returns
    to `AVAILABLE`, closing the availability cycle."
    PRD §3.7: "Cancellation always moves fulfillment to `CANCELLED` and releases the par of every
    `SELECTED` line (each line moves to `REMOVED` and returns its servings to its run, possibly
    flipping that run `SOLD_OUT → AVAILABLE`)."

    Design: Difficulty/non_linear_state_machine/production_run_cyclic_sold_out_to_available
    """
    ctx = setup_run5_box_selected5(api)  # run SOLD_OUT (par_remaining 0), one SELECTED item
    validate_success(api.cancel_box(ctx["box_id"], make_customer_headers(ctx["cust_id"])), 200)
    run = validate_success(api.get_production_run(ctx["run_id"], ADMIN), 200)
    assert run["status"] == "AVAILABLE"
    assert run["par_reserved"] == 0
    assert run["par_remaining"] == 5
    item = validate_success(api.get_box_item(ctx["item_id"], ADMIN), 200)
    assert item["status"] == "REMOVED"


def test_box_cancel_cascades_to_item_removed(api):
    """PRD §3.7: "Cancelling a still-`OPEN` box (permitted to the owning `Customer`) reflects
    that nothing has been charged: billing moves to `WAIVED`, the box's `refund_cents` is 0, and
    its `refund_destination` is `NONE`."
    PRD §3.7: "Cancellation always moves fulfillment to `CANCELLED` and releases the par of every
    `SELECTED` line (each line moves to `REMOVED` and returns its servings to its run".

    Design: Difficulty/transitive_cascade/box_cancel_release_par_flips_run_available_depth3
    """
    ctx = setup_run5_box_selected5(api)
    box = validate_success(api.cancel_box(ctx["box_id"], make_customer_headers(ctx["cust_id"])), 200)
    assert box["fulfillment_status"] == "CANCELLED"
    item = validate_success(api.get_box_item(ctx["item_id"], ADMIN), 200)
    assert item["status"] == "REMOVED"


def test_box_cancel_cascades_par_release_flips_run_available(api):
    """PRD §3.7: "releases the par of every `SELECTED` line (each line moves to `REMOVED` and
    returns its servings to its run, possibly flipping that run `SOLD_OUT → AVAILABLE`)."

    Design: Difficulty/transitive_cascade/box_cancel_release_par_flips_run_available_depth3
    """
    ctx = setup_run5_box_selected5(api)
    validate_success(api.cancel_box(ctx["box_id"], make_customer_headers(ctx["cust_id"])), 200)
    run = validate_success(api.get_production_run(ctx["run_id"], ADMIN), 200)
    assert run["par_reserved"] == 0
    assert run["status"] == "AVAILABLE"


def test_swap_releases_old_run_par(api):
    """PRD §3.4: "The existing item moves to `SWAPPED_OUT` and its reserved servings are released
    back to its run (which may flip that run `SOLD_OUT → AVAILABLE`), and a new `SELECTED` line
    is created for the `new_meal_id` with its own reserved par."

    Design: Difficulty/compensating_invariant/par_conservation_reserve_then_swap_out
    """
    ctx = setup_two_runs_box_item3(api)  # run1 (M1) reserved 3
    validate_success(api.swap_box_item(
        ctx["item_id"], swap_box_item_payload(ctx["m2_id"], 3),
        make_customer_headers(ctx["cust_id"])), 201)
    run1 = validate_success(api.get_production_run(ctx["run1_id"], ADMIN), 200)
    assert run1["par_reserved"] == 0
    assert run1["par_remaining"] == 10
    assert_par_conserved(run1)


def test_swap_reserves_new_run_par(api):
    """PRD §3.4: "a new `SELECTED` line is created for the `new_meal_id` with its own reserved
    par."
    PRD §2.8: "`par_reserved` is the sum of the `quantity` of every box item that is in
    `SELECTED` status and whose `reserved_run_id` points at this run."

    Design: Difficulty/compensating_invariant/par_conservation_reserve_then_swap_out
    """
    ctx = setup_two_runs_box_item3(api)
    validate_success(api.swap_box_item(
        ctx["item_id"], swap_box_item_payload(ctx["m2_id"], 3),
        make_customer_headers(ctx["cust_id"])), 201)
    run2 = validate_success(api.get_production_run(ctx["run2_id"], ADMIN), 200)
    assert run2["par_reserved"] == 3
    assert run2["par_remaining"] == 7
    assert_par_conserved(run2)


def test_run_cancel_grants_swap_credit_to_customer(api):
    """PRD §3.1: "the item is moved to `REMOVED`, its reserved servings are released back to the
    run (which may flip a `SOLD_OUT` run to `AVAILABLE`), and the affected customer is granted a
    swap credit equal to that line's `line_gross_cents`, written as a `SWAP_CREDIT` ledger
    entry."

    Design: Corner/cross_cutting_complexity_layers/run_cancel_cascades_swap_credit_to_customer
    """
    ctx = setup_open_run_box_selected3(api)  # M1 qty 3 -> line_gross 3 * 1099 = 3297c
    run = validate_success(api.cancel_production_run(ctx["run_id"], ADMIN), 200)
    assert run["status"] == "CANCELLED"
    item = validate_success(api.get_box_item(ctx["item_id"], ADMIN), 200)
    assert item["status"] == "REMOVED"
    customer = validate_success(api.get_customer(ctx["cust_id"], ADMIN), 200)
    assert customer["wallet_credit_cents"] == 3297


def test_buffer_check_is_per_line(api):
    """PRD §3.1: "Two runs on the same `line_code` may not have prep windows that overlap once
    each window is widened by the cleaning buffer, `LINE_BUFFER_MINUTES`, on both sides".
    (Complement: the buffer is scoped to a single `line_code`, so an overlapping window on a
    different line is admitted.)

    Design: Difficulty/resource_temporal_overlap/production_line_buffer_conflict
    """
    ctx = setup_run_on_line_l1(api)  # existing run on L1 [06:00, 10:00]
    resp = api.create_production_run(create_production_run_payload(
        ctx["m1_id"], line_code="L2",
        window_start="2026-03-14T06:00:00Z", window_end="2026-03-14T10:00:00Z"), ADMIN)
    validate_success(resp, 201)  # same window, different line -> no conflict


def test_open_already_available_run_invalid_transition(api):
    """PRD §3.1: "Opening a run advances it from `SCHEDULED` to `AVAILABLE`, at which point box
    items may reserve its servings".
    PRD §2.9: "(4) state validity, that the target resource is in a state from which the
    requested transition is defined, yielding `ERR_INVALID_STATE`".

    Design: Corner/state_machines/open_already_available_run_invalid_transition
    """
    meal = seed_meal(api, meal_code="M1", name="Meal 1")
    run = seed_run(api, meal["id"], open_run=True, par_total=100)  # now AVAILABLE
    resp = api.open_production_run(run["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
