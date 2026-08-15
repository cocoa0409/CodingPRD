"""Production routing: serial advance, skip rules, release guards, hold/resume."""
from test_helpers import (
    MGR,
    PLAN,
    ApiErrorId,
    accept_quote,
    complete_step,
    create_customer,
    create_full_sheet,
    create_grade,
    create_machine,
    create_submitted_quote,
    get_order,
    get_order_steps,
    get_step_by_station,
    release_order,
    validate_error,
    validate_success,
)

SIMPLE = {"bbox_width_mm": 50, "bbox_height_mm": 50, "hole_count": 0,
          "corner_fillet_count": 0, "bend_count": 0, "weld_inches": 0}
WITH_BEND = dict(SIMPLE, bend_count=1)


def _nested_order(line_overrides=None, stations=("LASER",)):
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    for st in stations:
        create_machine(st)
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=line_overrides or SIMPLE)
    return accept_quote(submitted["id"], customer["id"])


# --- serial advance (Corner: routing_serial_advance_laser_then_brake) -------

def test_routing_serial_advance_laser_then_brake(api):
    """PRD §3.6: "Advancement moves the next PENDING step to IN_PROGRESS; when
    that next step is the OUTSIDE_VENDOR step the order moves to
    AWAITING_OUTSIDE as §3.7 describes, and when no steps remain the order
    moves to INSPECTION." PRD §3.6: "Routing is strictly serial from then on:
    a step may enter IN_PROGRESS only when every lower-sequence step of the
    same order is COMPLETED or SKIPPED."

    Design: Corner/state_machines/routing_serial_advance_laser_then_brake
    """
    order = _nested_order(WITH_BEND, stations=("LASER", "BRAKE"))
    release_order(order["id"])

    steps = get_order_steps(order["id"])
    assert [s["station"] for s in steps] == ["LASER", "BRAKE"]
    assert steps[0]["status"] == "IN_PROGRESS"
    assert steps[1]["status"] == "PENDING"

    complete_step(steps[0]["id"])
    steps = get_order_steps(order["id"])
    assert steps[0]["status"] == "COMPLETED"
    assert steps[1]["status"] == "IN_PROGRESS"

    complete_step(steps[1]["id"])
    assert get_order(order["id"])["status"] == "INSPECTION"


# --- laser never skippable (Corner: laser_step_never_skippable) -------------

def test_laser_step_never_skippable(api):
    """PRD §3.6: "A `ProductionPlanner` may instead skip a step that is
    IN_PROGRESS, releasing its minutes and firing the same advancement — but
    cutting is never skippable, so skipping a LASER step is rejected with
    `ERR_STEP_NOT_SKIPPABLE` ..."

    Design: Corner/state_machines/laser_step_never_skippable
    """
    order = _nested_order()
    release_order(order["id"])
    laser = get_step_by_station(get_order_steps(order["id"]), "LASER")

    resp = api.skip_routing_step(laser["id"], PLAN)
    validate_error(resp, ApiErrorId.ERR_STEP_NOT_SKIPPABLE, 409)

    steps = get_order_steps(order["id"])
    assert get_step_by_station(steps, "LASER")["status"] == "IN_PROGRESS"


# --- complete from pending (Corner: error_step_complete_from_pending) -------

def test_complete_step_from_pending_rejected(api):
    """PRD §3.6: "A `MachineOperator` completes the step they are running;
    completing a step that is not IN_PROGRESS is rejected with
    `ERR_STEP_NOT_IN_PROGRESS`."

    Design: Corner/errors/error_step_complete_from_pending
    """
    order = _nested_order()  # never released: every step stays PENDING
    laser = get_step_by_station(get_order_steps(order["id"]), "LASER")
    assert laser["status"] == "PENDING"

    from test_helpers import TEST_USERS
    resp = api.complete_routing_step(laser["id"], TEST_USERS["operator_headers"])
    validate_error(resp, ApiErrorId.ERR_STEP_NOT_IN_PROGRESS, 409)


# --- machine down blocks release (Corner: machine_down_blocks_release) ------

def test_machine_down_blocks_release(api):
    """PRD §3.6: "Release to the floor is a `ProductionPlanner` act on a NESTED
    order — any other status is `ERR_ORDER_NOT_RELEASEABLE` — and it requires
    every routing step's machine to be ACTIVE, with a DOWN machine surfacing
    as `ERR_MACHINE_DOWN`."

    Design: Corner/endpoints/machine_down_blocks_release
    """
    grade = create_grade()
    customer = create_customer()
    create_full_sheet(grade["id"])
    laser_machine = create_machine("LASER")
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=SIMPLE)
    order = accept_quote(submitted["id"], customer["id"])

    validate_success(api.set_machine_status(laser_machine["id"], "DOWN", MGR))
    resp = api.release_order(order["id"], PLAN)
    validate_error(resp, ApiErrorId.ERR_MACHINE_DOWN, 409)
    assert get_order(order["id"])["status"] == "NESTED"


# --- hold/resume (Corner: hold_resume_roundtrip_restores_status) ------------

def test_hold_resume_roundtrip_restores_status(api):
    """PRD §3.6: "A `ProductionPlanner` can park an order that is in
    IN_PRODUCTION, AWAITING_OUTSIDE, or FINISHING — any other status is
    rejected with `ERR_ORDER_NOT_HOLDABLE` — by supplying a `hold_reason` of
    CAPACITY or VENDOR_DELAY, which is recorded on the order as it moves to
    ON_HOLD ..." PRD §3.6: "Resuming requires the order to be ON_HOLD
    (`ERR_ORDER_NOT_ON_HOLD` otherwise) and returns the order to the lifecycle
    status recorded in its last audit event before ORDER_HELD ..."

    Design: Corner/state_machines/hold_resume_roundtrip_restores_status
    """
    order = _nested_order()
    release_order(order["id"])

    held = validate_success(api.hold_order(order["id"], "CAPACITY", PLAN))
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "CAPACITY"

    resumed = validate_success(api.resume_order(order["id"], PLAN))
    assert resumed["status"] == "IN_PRODUCTION"
