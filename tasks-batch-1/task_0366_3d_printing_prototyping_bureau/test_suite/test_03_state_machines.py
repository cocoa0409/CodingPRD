"""State machines: PrintRun failure/reprint cycle, Order parallel axes,
PrintFile branching, and invalid/guarded transitions.

Covers:
  Difficulty/non_linear_state_machine/printrun_failure_reprint_cycle
  Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_axes
  Corner/state_machines/confirm_already_confirmed_returns_invalid_state
  Corner/state_machines/ship_before_ready_returns_order_not_ready
  Corner/state_machines/ship_ready_without_shipment_returns_no_shipment
  Corner/state_machines/cancel_confirmed_after_production_started_returns_production_started
  Corner/state_machines/printfile_initial_state_uploaded
  Corner/state_machines/check_rejected_file_is_terminal_lockdown
  Corner/entities/order_system_fields_ignored_on_create
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    api_client, setup_catalogue, setup_confirmed_order, setup_run_failed,
    setup_run_printing, setup_ready_order_with_shipment, adjudicate_run,
    get_reprint_line, create_run, refresh_order, upload_file, upload_and_check_file,
    create_order_payload, FILE_B, TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
QA = TEST_USERS["qa_reviewer_headers"]


def test_printrun_failure_spawns_reprint_line_and_requeues(api):
    """PRD §3.7: "The system spawns a reprint `OrderLine` as a copy of the failed
    line, setting that new line's `reprint_of_line_id` to the failed line's id (a
    self-referential reprint chain) and its `reprint_cause` to the recorded fail
    cause."
    PRD §3.7: "Adjudication advances the run's `version` by 1, transitions it from
    `FAILED` back to `QUEUED`, and creates a fresh `QUEUED` print run for the
    reprint line on the machine, spool, and slot supplied with the adjudication
    request".

    Design: Difficulty/non_linear_state_machine/printrun_failure_reprint_cycle
    """
    env = setup_run_failed("OPERATOR_ERROR", geometry=FILE_B, layer_height_mm=0.10,
                           quantity=1, duration_min=24, spool_grams=1000)
    failed_line = env["line"]
    adjudicate_run(env, start_min=30, duration_min=24)

    reprint = get_reprint_line(env, failed_line=failed_line)
    assert reprint is not None, "reprint line must exist"
    assert reprint["reprint_of_line_id"] == failed_line["id"]
    assert reprint["reprint_cause"] == "OPERATOR_ERROR"

    # A new QUEUED PrintRun for the reprint line closes the cycle.
    runs, _ = _list(api.list_print_runs(QA, params={
        "order_line_id": reprint["id"], "status": "QUEUED"}))
    assert len(runs) >= 1, "reprint line should have a QUEUED run"
    assert runs[0]["status"] == "QUEUED"


def test_failed_run_is_nonterminal_and_reopens_via_adjudicate(api):
    """PRD §3.7: "Failure is not terminal — it opens a reprint cycle."
    PRD §3.7: "Adjudication advances the run's `version` by 1, transitions it from
    `FAILED` back to `QUEUED`".

    Design: Difficulty/non_linear_state_machine/printrun_failure_reprint_cycle
    """
    env = setup_run_failed("FILE_DEFECT", geometry=FILE_B, layer_height_mm=0.10,
                           quantity=1, duration_min=24, spool_grams=1000)
    assert env["run"]["status"] == "FAILED"
    failed_version = env["run"]["version"]
    adjudicate_run(env, start_min=30, duration_min=24)
    assert env["run"]["status"] == "QUEUED"
    assert env["run"]["version"] == failed_version + 1, env["run"]["version"]


def test_order_axes_advance_independently_confirm_and_ship(api):
    """PRD §3.5: "On success, the order's `payment_status` becomes `ESCROWED`, the
    order's `fulfillment_status` becomes `CONFIRMED`".
    PRD §3.8: "On success the order's `fulfillment_status` becomes `SHIPPED` and
    its `payment_status` becomes `CAPTURED`".

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_axes
    """
    env = setup_ready_order_with_shipment(geometry=FILE_B, layer_height_mm=0.10,
                                          quantity=1, duration_min=24, spool_grams=1000)
    before = env["order"]
    assert before["fulfillment_status"] == "READY"
    assert before["payment_status"] == "ESCROWED"

    res = api.ship_order(before["id"], {"expected_order_version": before["version"]}, OPERATOR)
    after = validate_success(res, 200)
    assert after["fulfillment_status"] == "SHIPPED"
    assert after["payment_status"] == "CAPTURED"


def test_confirm_sets_confirmed_and_escrowed(api):
    """PRD §3.5: "On success, the order's `payment_status` becomes `ESCROWED`, the
    order's `fulfillment_status` becomes `CONFIRMED`, the customer's
    `wallet_balance_cents` is reduced by `grand_total_cents` and `escrow_held_cents`
    is raised by the same amount, and the order's `version` increases by 1."

    Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_payment_axes
    """
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1)
    order = env["order"]
    assert order["fulfillment_status"] == "CONFIRMED"
    assert order["payment_status"] == "ESCROWED"


def test_confirm_already_confirmed_rejected_invalid_state(api):
    """PRD §2.11: "(6) state legality — the target resource is in a state from
    which the requested transition is permitted, else `ERR_INVALID_STATE`."
    PRD §3.5: "Confirming a quoted order is the moment money moves into escrow."

    Design: Corner/state_machines/confirm_already_confirmed_returns_invalid_state
    """
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1)
    order = env["order"]
    res = api.confirm_order(order["id"], {"expected_order_version": order["version"]},
                            env["cust_headers"])
    validate_error(res, "ERR_INVALID_STATE")


def test_ship_before_ready_rejected_order_not_ready(api):
    """PRD §3.8: "the `fulfillment_status` must be `READY`, otherwise it is
    rejected with `ERR_ORDER_NOT_READY`".

    Design: Corner/state_machines/ship_before_ready_returns_order_not_ready
    """
    env = setup_confirmed_order(geometry=FILE_B, layer_height_mm=0.10, quantity=1)
    api_client.create_shipment(
        {"order_id": env["order"]["id"], "carrier": "UPS", "tracking_number": "1Z0"},
        OPERATOR)
    order = refresh_order(env)
    res = api.ship_order(order["id"], {"expected_order_version": order["version"]}, OPERATOR)
    validate_error(res, "ERR_ORDER_NOT_READY")


def test_ship_ready_without_shipment_rejected_no_shipment(api):
    """PRD §3.8: "a `Shipment` with status `CREATED` must exist for the order,
    otherwise it is rejected with `ERR_NO_SHIPMENT`."

    Design: Corner/state_machines/ship_ready_without_shipment_returns_no_shipment
    """
    env = setup_run_printing(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                             duration_min=24, spool_grams=1000)
    get_success_data(api_client.complete_print_run(env["run"]["id"], OPERATOR))
    order = refresh_order(env)
    assert order["fulfillment_status"] == "READY"
    res = api.ship_order(order["id"], {"expected_order_version": order["version"]}, OPERATOR)
    validate_error(res, "ERR_NO_SHIPMENT")


def test_cancel_confirmed_after_production_started_rejected(api):
    """PRD §3.5: "From `CONFIRMED` the cancel is constrained — it is permitted only
    when no print run for any of the order's lines is in `PRINTING` or `DONE`; if
    production has progressed that far, the cancel is rejected with
    `ERR_PRODUCTION_STARTED`."

    Once a run is PRINTING, PRD §3.6 has already bubbled the owning order from
    `CONFIRMED` to `IN_PRODUCTION` ("if the owning order is still `CONFIRMED` it
    bubbles up to `IN_PRODUCTION`"). The PRD names `ERR_PRODUCTION_STARTED` as the
    rejection for cancel once production has progressed, but does not state that the
    cancel state-gate is opened to `IN_PRODUCTION`; a faithful PRD-only reader could
    treat the no-longer-`CONFIRMED` order as failing the (6) state-legality check
    (`ERR_INVALID_STATE`) per §2.11. Both readings are PRD-supported, so either
    rejection is accepted (PRD only names a member of the set, not the choice).

    Design: Corner/state_machines/cancel_confirmed_after_production_started_returns_production_started
    """
    env = setup_run_printing(geometry=FILE_B, layer_height_mm=0.10, quantity=1,
                             duration_min=24, spool_grams=1000)
    res = api.cancel_order(env["order"]["id"], env["cust_headers"])
    validate_error_is_one_of(res, ["ERR_PRODUCTION_STARTED", "ERR_INVALID_STATE"])


def test_printfile_initial_state_uploaded(api):
    """PRD §3.2: "A freshly uploaded file is in status `UPLOADED` with no
    printability score yet assigned."

    Design: Corner/state_machines/printfile_initial_state_uploaded
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    f = upload_file(env["bureau"]["id"], env["customer"]["id"], geometry=FILE_B)
    assert f["status"] == "UPLOADED"


def test_rejected_file_override_rejected_invalid_state(api):
    """PRD §3.2: "`REJECTED` is a terminal state."
    PRD §3.2: "the override is only permitted while the file is `FLAGGED`".

    Design: Corner/state_machines/check_rejected_file_is_terminal_lockdown
    """
    env = setup_catalogue(with_spool=False)
    geo = dict(FILE_B)
    geo["is_manifold"] = False
    checked = upload_and_check_file(env["bureau"]["id"], env["customer"]["id"],
                                    env["material"]["id"], geometry=geo)
    assert checked["status"] == "REJECTED"
    res = api.override_print_file(checked["id"], QA)
    validate_error(res, "ERR_INVALID_STATE")


def test_order_system_fields_forced_on_create(api):
    """PRD §3.3: "A new order begins with `fulfillment_status` of `DRAFT`,
    `payment_status` of `UNPAID`, and all monetary totals at zero."
    PRD §2.4: "The `version` begins at 1 at creation".

    Design: Corner/entities/order_system_fields_ignored_on_create
    """
    env = setup_catalogue(with_spool=False, with_machine=False)
    res = api.create_order(
        create_order_payload(env["bureau"]["id"], env["customer"]["id"], lead_tier="STANDARD"),
        env["cust_headers"])
    order = validate_success(res, 201)
    assert order["fulfillment_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["grand_total_cents"] == 0
    assert order["version"] == 1


def _list(response):
    body = response.json()
    return body.get("data", []), body.get("meta", {})
