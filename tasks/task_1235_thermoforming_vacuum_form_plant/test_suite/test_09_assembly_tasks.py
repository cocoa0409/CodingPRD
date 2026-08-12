"""Secondary assembly and packing gates (PRD §3.8)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    complete_run,
    complete_task,
    create_booth,
    create_certified_lot,
    create_custom_spec,
    create_order,
    create_spec_decide_payload,
    create_station,
    create_task,
    create_tool_production,
    disposition_inspection_ok,
    get_order,
    get_task,
    record_inspection,
    reserve_virgin,
    schedule_run,
    setup_running_order,
    stage_order,
    validate_error,
    validate_success,
)

_MANAGER = TEST_USERS["plant_manager_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]


def test_assembly_complete_out_of_sequence_rejected(api):
    """PRD §3.8: "The task must be `PENDING` (otherwise
    `ERR_INVALID_TASK_STATE`); the order's schedule must be `RUNNING`,
    `ON_HOLD`, or `COMPLETED` (otherwise `ERR_INVALID_ORDER_STATE`); and every
    task of the same order with a lower `sequence_no` must already be
    `COMPLETED`, otherwise `ERR_ASSEMBLY_SEQUENCE_VIOLATION`."

    Completing sequence 2 while sequence 1 is still PENDING violates the
    ordered secondary-operations chain.

    Design: Corner/validations/assembly_complete_out_of_sequence_rejected
    """
    ctx = setup_running_order(
        alloc_qty_kg=2.950,
        order_overrides={"order_code": "O-V10", "ordered_qty": 50},
        lot_overrides={"lot_code": "L-V10"},
        tool_overrides={"tool_code": "T-V10", "part_number": "P-V10"},
    )
    task1 = create_task(ctx["order"]["id"], task_type="TRIM", sequence_no=1)
    task2 = create_task(
        ctx["order"]["id"], task_type="INSERT", sequence_no=2, insert_part_code="INS-42"
    )

    res = api.complete_assembly_task(task2["id"], _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_ASSEMBLY_SEQUENCE_VIOLATION)
    assert get_task(task2["id"])["status"] == "PENDING", (
        "the out-of-sequence completion must not transition the task"
    )


def test_pack_complete_before_quality_release_rejected(api):
    """PRD §3.8: "A `PACK` task carries two additional gates: the order's
    `quality_status` must be `RELEASED` (otherwise
    `ERR_ORDER_QUALITY_NOT_RELEASED`), and the order's packaging spec must be
    `ACTIVE` or `APPROVED` (otherwise `ERR_PACK_SPEC_NOT_APPROVED`) — packing
    against a spec still awaiting decision, or one already rejected, is not
    permitted."

    Quality is still PENDING (no inspection was ever dispositioned), the spec
    is ACTIVE, and the sequence order is respected: only the quality gate
    fails.

    Design: Corner/validations/pack_complete_before_quality_release_rejected
    """
    ctx = setup_running_order(
        alloc_qty_kg=2.950,
        order_overrides={"order_code": "O-V11", "ordered_qty": 50},
        lot_overrides={"lot_code": "L-V11"},
        tool_overrides={"tool_code": "T-V11", "part_number": "P-V11"},
        spec_overrides={"spec_code": "S-V11"},
    )
    task1 = create_task(ctx["order"]["id"], task_type="TRIM", sequence_no=1)
    task2 = create_task(ctx["order"]["id"], task_type="PACK", sequence_no=2)
    complete_task(task1["id"])

    res = api.complete_assembly_task(task2["id"], _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_ORDER_QUALITY_NOT_RELEASED)


def test_assembly_task_double_complete_rejected(api):
    """PRD §3.8: "The task must be `PENDING` (otherwise
    `ERR_INVALID_TASK_STATE`)"
    PRD §3.8: "Completion moves the task to the terminal `COMPLETED` state and
    advances its `version`."

    Design: Corner/state_machines/assembly_task_double_complete_rejected
    """
    ctx = setup_running_order(
        alloc_qty_kg=2.950,
        order_overrides={"order_code": "O-S7", "ordered_qty": 50},
        lot_overrides={"lot_code": "L-S7"},
        tool_overrides={"tool_code": "T-S7", "part_number": "P-S7"},
    )
    task = create_task(ctx["order"]["id"], task_type="TRIM", sequence_no=1)
    completed = complete_task(task["id"])
    assert completed["status"] == "COMPLETED"

    res = api.complete_assembly_task(task["id"], _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_INVALID_TASK_STATE)


def _setup_completed_order_with_rejected_spec(api):
    """CUSTOM spec created (PENDING_APPROVAL), order opened against it while
    that is still legal (PRD §3.5), spec then REJECTED; the order is run to
    COMPLETED with quality RELEASED; TRIM (seq 1) is COMPLETED and PACK
    (seq 2) is PENDING."""
    spec = create_custom_spec(spec_code="PS-C", per_pack_cost=1.10)
    lot = create_certified_lot(lot_code="LP")
    tool = create_tool_production(
        tool_code="TPK", part_number="P-PK", tool_type="MATCHED_SET",
        prototype_cost=1200.00, production_cost=8000.00, rated_lifetime_shots=80000,
    )
    station = create_station(resource_code="ST-P")
    booth = create_booth(resource_code="B-P")
    order = create_order(tool, spec, order_code="OP", ordered_qty=100)

    validate_success(
        api.decide_packaging_spec(spec["id"], create_spec_decide_payload("REJECTED"), _MANAGER),
        200,
    )

    reserve_virgin(order["id"], lot["id"], 5.900)
    stage_order(order["id"])
    run = schedule_run(
        order["id"], station["id"],
        start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z",
        cycle_time_s=28, shots_planned=100,
    )
    complete_run(run["id"], 100, 0.000, actual_end="2026-05-02T11:00:00Z")
    insp = record_inspection(
        order["id"], booth["id"], inspection_type="FINAL",
        window=("2026-05-02T12:00:00Z", "2026-05-02T12:30:00Z"),
    )
    disposition_inspection_ok(insp["id"], "PASS")

    task_trim = create_task(order["id"], task_type="TRIM", sequence_no=1)
    task_pack = create_task(order["id"], task_type="PACK", sequence_no=2)
    complete_task(task_trim["id"])
    return {"order": get_order(order["id"]), "spec": spec,
            "task_trim": task_trim, "task_pack": task_pack}


def test_pack_task_blocked_by_rejected_packaging_spec(api):
    """PRD §3.8: "A `PACK` task carries two additional gates: the order's
    `quality_status` must be `RELEASED` (otherwise
    `ERR_ORDER_QUALITY_NOT_RELEASED`), and the order's packaging spec must be
    `ACTIVE` or `APPROVED` (otherwise `ERR_PACK_SPEC_NOT_APPROVED`) — packing
    against a spec still awaiting decision, or one already rejected, is not
    permitted."
    PRD §3.5: "The referenced packaging spec must be `ACTIVE`,
    `PENDING_APPROVAL`, or `APPROVED`; creating an order against a `REJECTED`
    spec is `ERR_PACK_SPEC_NOT_APPROVED`."

    The order was created while its CUSTOM spec was still PENDING_APPROVAL
    (legal at creation), the spec was then REJECTED, and every order-local
    gate (COMPLETED schedule, RELEASED quality, sequence order) passes — the
    spec gate alone blocks the pack.

    Design: Difficulty/cross_entity_state_dependency/pack_task_blocked_by_rejected_packaging_spec
    """
    ctx = _setup_completed_order_with_rejected_spec(api)
    assert ctx["order"]["schedule_status"] == "COMPLETED"
    assert ctx["order"]["quality_status"] == "RELEASED"

    res = api.complete_assembly_task(ctx["task_pack"]["id"], _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_PACK_SPEC_NOT_APPROVED)


def test_pack_task_remains_pending_after_spec_gate_rejection(api):
    """PRD §3.8: "Completion moves the task to the terminal `COMPLETED` state
    and advances its `version`."
    PRD §3.8: "the order's packaging spec must be `ACTIVE` or `APPROVED`
    (otherwise `ERR_PACK_SPEC_NOT_APPROVED`)"

    A rejected PACK attempt performs no transition: the task remains PENDING
    and the already-COMPLETED order is untouched.

    Design: Difficulty/cross_entity_state_dependency/pack_task_blocked_by_rejected_packaging_spec
    """
    ctx = _setup_completed_order_with_rejected_spec(api)

    validate_error(
        api.complete_assembly_task(ctx["task_pack"]["id"], _SCHEDULER),
        ApiErrorId.ERR_PACK_SPEC_NOT_APPROVED,
    )
    pack_after = get_task(ctx["task_pack"]["id"])
    assert pack_after["status"] == "PENDING", (
        f"the rejected pack completion must leave the task PENDING, got {pack_after['status']}"
    )
    order_after = get_order(ctx["order"]["id"])
    assert order_after["schedule_status"] == "COMPLETED"
    assert order_after["quality_status"] == "RELEASED"
