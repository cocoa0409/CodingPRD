"""First-piece inspection: flatness boundary, rework loop, SoD, RBAC."""
from test_helpers import (
    ApiErrorId,
    accept_quote,
    assert_inspection_report,
    complete_inhouse_steps,
    create_customer,
    create_full_sheet,
    create_grade,
    create_machine,
    create_submitted_quote,
    get_order,
    get_order_steps,
    get_step_by_station,
    list_audit_events,
    make_operator_headers,
    make_qc_inspector_headers,
    release_order,
    submit_inspection,
    validate_error,
    validate_success,
)

SIMPLE = {"bbox_width_mm": 100, "bbox_height_mm": 100, "hole_count": 0,
          "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0}
WITH_BEND = dict(SIMPLE, bend_count=2)


def _order_at_inspection(line_overrides=None, stations=("LASER",),
                         operator_id="op-default"):
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    for st in stations:
        create_machine(st)
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=line_overrides or SIMPLE)
    order = accept_quote(submitted["id"], customer["id"])
    release_order(order["id"])
    complete_inhouse_steps(order["id"], operator_id)
    assert get_order(order["id"])["status"] == "INSPECTION"
    return {"grade": grade, "customer": customer, "order": order}


# --- flatness boundary (Difficulty: flatness_ratio_exactly_at_limit_passes) -

def test_flatness_exactly_at_limit_passes(api):
    """PRD §3.8: "the report's `result` is PASS if and only if that ratio is
    at most 0.0015 — one-and-a-half tenths of a percent — and
    `dimensional_pass` is true. The boundary is inclusive: a ratio of exactly
    0.0015 passes, and anything strictly greater fails."

    Design: Difficulty/boundary_precision_check/flatness_ratio_exactly_at_limit_passes
    """
    world = _order_at_inspection()
    order = world["order"]

    # 0.6 / 400 == exactly 0.0015 (inclusive boundary).
    resp = submit_inspection(order["id"], deviation_mm=0.6, diagonal_mm=400)
    report = validate_success(resp, 201)
    assert_inspection_report(report)
    assert report["result"] == "PASS"
    assert get_order(order["id"])["status"] == "COMPLETED"


def test_flatness_above_limit_fails(api):
    """PRD §3.8: "The boundary is inclusive: a ratio of exactly 0.0015 passes,
    and anything strictly greater fails." PRD §3.8: "A failing report starts
    the rework loop instead: the routing steps for the stations implicated by
    the failure reset from COMPLETED back to PENDING, their reserved minutes
    are re-booked on the same machine through capacity booking, the order
    returns to IN_PRODUCTION ..."

    Design: Difficulty/boundary_precision_check/flatness_ratio_exactly_at_limit_passes
    """
    world = _order_at_inspection()
    order = world["order"]

    # 0.61 / 400 == 0.001525 > 0.0015.
    resp = submit_inspection(order["id"], deviation_mm=0.61, diagonal_mm=400)
    report = validate_success(resp, 201)
    assert report["result"] == "FAIL"
    assert get_order(order["id"])["status"] == "IN_PRODUCTION"


# --- rework loop (Difficulty: order_inspection_fail_rework_loop) ------------

def test_inspection_fail_enters_rework_loop(api):
    """PRD §3.8: "A failing report starts the rework loop instead: the routing
    steps for the stations implicated by the failure reset from COMPLETED back
    to PENDING, their reserved minutes are re-booked on the same machine
    through capacity booking, the order returns to IN_PRODUCTION, and an
    INSPECTION_FAIL_REWORK audit event is appended ..."

    Design: Difficulty/non_linear_state_machine/order_inspection_fail_rework_loop
    """
    world = _order_at_inspection()
    order = world["order"]

    # 0.8 / 400 == 0.002 > 0.0015 -> FAIL.
    resp = submit_inspection(order["id"], deviation_mm=0.8, diagonal_mm=400)
    report = validate_success(resp, 201)
    assert report["result"] == "FAIL"

    order_mid = get_order(order["id"])
    assert order_mid["status"] == "IN_PRODUCTION", "rework is not terminal"

    laser = get_step_by_station(get_order_steps(order["id"]), "LASER")
    assert laser["status"] in ("PENDING", "IN_PROGRESS"), (
        "implicated steps reset from COMPLETED back toward PENDING"
    )


def test_rework_loop_terminates_via_pass(api):
    """PRD §3.8: "... the order then works its way back through the serial
    chain toward a fresh inspection." PRD §3.8: "A passing report completes
    the order: the order moves from INSPECTION to COMPLETED, `completed_at` is
    stamped from the logical clock, and an ORDER_COMPLETED audit event is
    appended."

    Design: Difficulty/non_linear_state_machine/order_inspection_fail_rework_loop
    """
    world = _order_at_inspection()
    order = world["order"]

    validate_success(
        submit_inspection(order["id"], deviation_mm=0.8, diagonal_mm=400), 201)

    # The serial chain restarts: complete the reset steps again, fail once
    # more, then pass.
    complete_inhouse_steps(order["id"])
    validate_success(
        submit_inspection(order["id"], deviation_mm=0.8, diagonal_mm=400), 201)
    complete_inhouse_steps(order["id"])

    resp = submit_inspection(order["id"], deviation_mm=0.5, diagonal_mm=400)
    report = validate_success(resp, 201)
    assert report["result"] == "PASS"
    final = get_order(order["id"])
    assert final["status"] == "COMPLETED"
    assert final.get("completed_at"), "completed_at stamped from logical clock"


# --- fail cascade (Difficulty: inspection_fail_cascade_resets_steps_and_rebooks_capacity)

def test_inspection_fail_resets_steps_and_records_audit(api):
    """PRD §3.8: "A failing report starts the rework loop instead: the routing
    steps for the stations implicated by the failure reset from COMPLETED back
    to PENDING, their reserved minutes are re-booked on the same machine
    through capacity booking, the order returns to IN_PRODUCTION, and an
    INSPECTION_FAIL_REWORK audit event is appended ..."

    Design: Difficulty/transitive_cascade/inspection_fail_cascade_resets_steps_and_rebooks_capacity
    """
    world = _order_at_inspection(WITH_BEND, stations=("LASER", "BRAKE"))
    order = world["order"]

    resp = submit_inspection(order["id"], deviation_mm=1.0, diagonal_mm=400)
    assert validate_success(resp, 201)["result"] == "FAIL"

    assert get_order(order["id"])["status"] == "IN_PRODUCTION"
    steps = get_order_steps(order["id"])
    for step in steps:
        assert step["status"] != "COMPLETED", (
            f"{step['station']} step must be reset by the rework loop"
        )

    events = list_audit_events({"entity_id": order["id"],
                                "event_type": "INSPECTION_FAIL_REWORK"})
    assert len(events) >= 1, "INSPECTION_FAIL_REWORK audit event recorded"
    assert all(e["entity_id"] == order["id"] for e in events)


def test_reworked_order_completes_after_second_pass(api):
    """PRD §3.8: "A failing report starts the rework loop instead: the routing
    steps for the stations implicated by the failure reset from COMPLETED back
    to PENDING, their reserved minutes are re-booked on the same machine
    through capacity booking, the order returns to IN_PRODUCTION, and an
    INSPECTION_FAIL_REWORK audit event is appended — the order then works its
    way back through the serial chain toward a fresh inspection." PRD §3.8:
    "A passing report completes the order: the order moves from INSPECTION to
    COMPLETED, `completed_at` is stamped from the logical clock, and an
    ORDER_COMPLETED audit event is appended."

    Design: Difficulty/transitive_cascade/inspection_fail_cascade_resets_steps_and_rebooks_capacity
    """
    world = _order_at_inspection(WITH_BEND, stations=("LASER", "BRAKE"))
    order = world["order"]

    validate_success(
        submit_inspection(order["id"], deviation_mm=1.0, diagonal_mm=400), 201)

    complete_inhouse_steps(order["id"])
    resp = submit_inspection(order["id"], deviation_mm=0.5, diagonal_mm=400)
    assert validate_success(resp, 201)["result"] == "PASS"
    assert get_order(order["id"])["status"] == "COMPLETED"


# --- SoD + role gate (Corner: operator_cannot_inspect_and_inspector_cannot_complete)

def test_inspection_role_gate_and_segregation_of_duties(api):
    """PRD §3.8: "The submitting inspector's `X-User-ID` is recorded as
    `inspector_id`, and segregation of duties is enforced: the inspector must
    differ from the operator recorded as `completing_operator_id` on the
    order's last completed routing step, or the submission is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403)." PRD §2.1: "A caller whose role is not in
    the endpoint's list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/operator_cannot_inspect_and_inspector_cannot_complete
    """
    world = _order_at_inspection(operator_id="op-1")
    order = world["order"]
    payload = {"flatness_deviation_mm": 0.5, "measured_diagonal_mm": 400,
               "dimensional_pass": True}

    # MachineOperator is not on the inspection endpoint's role list.
    resp = api.submit_inspection_report(order["id"], payload,
                                        make_operator_headers("op-2"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    # A QCInspector whose id equals the completing operator's violates SoD.
    resp = api.submit_inspection_report(order["id"], payload,
                                        make_qc_inspector_headers("op-1"))
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)

    # A different inspector inspects successfully.
    resp = api.submit_inspection_report(order["id"], payload,
                                        make_qc_inspector_headers("qc-9"))
    report = validate_success(resp, 201)
    assert report["result"] == "PASS"
    assert report["inspector_id"] == "qc-9"
    assert get_order(order["id"])["status"] == "COMPLETED"
