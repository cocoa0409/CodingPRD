"""Forming runs, station window semantics, and the resume re-validation gate
(PRD §3.6)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_forming_run,
    complete_run,
    create_certified_lot,
    create_forming_run_payload,
    create_order,
    create_station,
    create_stock_spec,
    create_approve_production_payload,
    create_tool_production,
    create_tool_prototype,
    get_allocation,
    get_order,
    get_success_data,
    reserve_virgin,
    schedule_run,
    setup_running_order,
    setup_staged_order,
    stage_order,
    validate_error,
    validate_success,
)

_PLANNER = TEST_USERS["materials_planner_headers"]
_ENGINEER = TEST_USERS["tooling_engineer_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]


def test_first_run_creation_flips_order_to_running(api):
    """PRD §3.6: "A new run is born `SCHEDULED`, and the order's very first
    run flips the order `STAGED` → `RUNNING` and advances the order's
    `version`."

    Design: Corner/state_machines/first_run_creation_flips_order_to_running
    """
    ctx = setup_staged_order()
    assert ctx["order"]["schedule_status"] == "STAGED"
    station = create_station(resource_code="ST-S5")

    run = validate_success(
        api.create_forming_run(
            create_forming_run_payload(
                ctx["order"]["id"], station["id"],
                planned_start="2026-05-02T10:00:00Z",
                planned_end="2026-05-02T10:30:00Z",
                shots_planned=10,
            ),
            _SCHEDULER,
        ),
        201,
    )
    assert_forming_run(run)
    assert run["status"] == "SCHEDULED", f"new run must be born SCHEDULED, got {run['status']}"

    order = get_order(ctx["order"]["id"])
    assert order["schedule_status"] == "RUNNING", (
        f"the first run must flip the order to RUNNING, got {order['schedule_status']}"
    )


def test_run_create_on_queued_order_rejected(api):
    """PRD §3.6: "The order must be `STAGED` or `RUNNING` — otherwise
    `ERR_ORDER_NOT_RUNNING`."

    Design: Corner/errors/run_create_on_queued_order_rejected
    """
    tool = create_tool_prototype(tool_code="T-ERR4", part_number="P-ERR4")
    spec = create_stock_spec(spec_code="S-ERR4")
    station = create_station(resource_code="ST-ERR4")
    order = create_order(tool, spec, order_code="O-ERR4", ordered_qty=50)
    assert order["schedule_status"] == "QUEUED"

    res = api.create_forming_run(
        create_forming_run_payload(order["id"], station["id"]),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_RUNNING)


def test_run_window_inverted_returns_invalid_request(api):
    """PRD §2.9: "Range rules require `spec_min_wall_mm` no greater than
    `spec_nominal_wall_mm`, `expires_at` later than `issued_at`, `planned_end`
    later than `planned_start`, `scheduled_end` later than `scheduled_start`,
    and `max_gauge_mm` no less than `min_gauge_mm`."
    PRD §2.9: "When several rules could reject the same request, checks are
    evaluated in a fixed priority order, and the earliest failing check
    determines the error returned."

    The inverted window is a schema-tier violation, detected before existence
    checks (both referenced ids deliberately do not exist).

    Design: Corner/validations/run_window_inverted_returns_invalid_request
    """
    res = api.create_forming_run(
        create_forming_run_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            planned_start="2026-05-02T11:00:00Z",
            planned_end="2026-05-02T10:00:00Z",
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_resume_rejected_when_review_allocation_unrecoverable(api):
    """PRD §3.6: "It requires the order to be `ON_HOLD` (otherwise
    `ERR_INVALID_ORDER_STATE`) and the tool to be `PROTOTYPE` or `PRODUCTION`
    again (otherwise `ERR_TOOL_NOT_QUALIFIED`). Then every allocation of the
    order sitting in `REVIEW` is re-validated: for a virgin allocation the lot
    must be `CERTIFIED` with `available_kg` at least the allocation's
    `qty_kg`; for a regrind allocation the batch must still be allocatable."
    PRD §3.6: "If any allocation fails, the resume is rejected with
    `ERR_ALLOCATION_REVIEW_FAILED` and the order stays `ON_HOLD`."

    The tool revision forces the hold; the lot block makes the REVIEW
    allocation unrecoverable. The tool is re-qualified first so the resume
    reaches the re-validation gate (the PRD checks the tool before
    re-validating allocations).

    Design: Corner/cross_cutting_layers/resume_rejected_when_review_allocation_unrecoverable
    """
    ctx = setup_running_order(
        tool_overrides={"tool_code": "T-CC3", "part_number": "P-CC3", "prototype_cost": 1000.00},
        order_overrides={"order_code": "O-CC3"},
        lot_overrides={"lot_code": "L-CC3"},
    )
    order_id = ctx["order"]["id"]
    assert ctx["order"]["schedule_status"] == "RUNNING"

    # Tool revision cascade: order RUNNING -> ON_HOLD, allocation RESERVED -> REVIEW.
    get_success_data(api.revise_tool(ctx["tool"]["id"], _ENGINEER))
    assert get_order(order_id)["schedule_status"] == "ON_HOLD"
    assert get_allocation(ctx["allocation"]["id"])["status"] == "REVIEW"

    # Contamination event: the source lot leaves CERTIFIED.
    get_success_data(api.block_material_lot(ctx["lot"]["id"], _PLANNER))

    # Re-qualify the tool so the resume reaches the re-validation gate.
    get_success_data(api.submit_qualification(ctx["tool"]["id"], _ENGINEER))
    get_success_data(
        api.approve_production(
            ctx["tool"]["id"],
            create_approve_production_payload(production_cost=8100.00, rated_lifetime_shots=80000),
            _ENGINEER,
        )
    )

    res = api.resume_order(order_id, _SCHEDULER)
    validate_error(res, ApiErrorId.ERR_ALLOCATION_REVIEW_FAILED)

    order_after = get_order(order_id)
    assert order_after["schedule_status"] == "ON_HOLD", (
        f"the hold must not be released when re-validation fails, got {order_after['schedule_status']}"
    )
    alloc_after = get_allocation(ctx["allocation"]["id"])
    assert alloc_after["status"] == "REVIEW", (
        f"the failed allocation must stay in REVIEW, got {alloc_after['status']}"
    )


def test_station_back_to_back_runs_allowed(api):
    """PRD §3.6: "A new run conflicts with another run on the same station
    only if that run is still `SCHEDULED` and the two windows genuinely
    intersect — that is, unless the new window ends no later than the existing
    window's start or begins no earlier than the existing window's end."
    PRD §3.6: "Back-to-back scheduling is explicitly allowed: a new run
    starting at exactly the instant another run ends does not conflict."

    Design: Difficulty/resource_temporal_overlap/station_half_open_adjacency_vs_overlap
    """
    ctx = setup_staged_order(
        alloc_qty_kg=9.900,
        order_overrides={"order_code": "OS", "ordered_qty": 150},
        lot_overrides={"lot_code": "LS"},
        tool_overrides={"tool_code": "TS", "part_number": "P-S", "prototype_cost": 1200.00},
        spec_overrides={"spec_code": "S-S"},
    )
    station = create_station(resource_code="ST-H")
    order_id = ctx["order"]["id"]

    run1 = validate_success(
        api.create_forming_run(
            create_forming_run_payload(
                order_id, station["id"],
                planned_start="2026-05-02T10:00:00Z",
                planned_end="2026-05-02T11:00:00Z",
                shots_planned=100,
            ),
            _SCHEDULER,
        ),
        201,
    )
    run2 = validate_success(
        api.create_forming_run(
            create_forming_run_payload(
                order_id, station["id"],
                planned_start="2026-05-02T11:00:00Z",
                planned_end="2026-05-02T12:00:00Z",
                shots_planned=100,
            ),
            _SCHEDULER,
        ),
        201,
    )
    assert run1["status"] == "SCHEDULED" and run2["status"] == "SCHEDULED", (
        "back-to-back windows [10:00,11:00) and [11:00,12:00) must both schedule"
    )


def test_station_intersecting_window_rejected(api):
    """PRD §3.6: "Such a conflict is rejected with
    `ERR_STATION_WINDOW_OVERLAP`."

    The window [10:30,11:30) genuinely intersects the existing SCHEDULED run's
    [10:00,11:00) window on the same station.

    Design: Difficulty/resource_temporal_overlap/station_half_open_adjacency_vs_overlap
    """
    ctx = setup_staged_order(
        alloc_qty_kg=9.900,
        order_overrides={"order_code": "OS2", "ordered_qty": 150},
    )
    station = create_station(resource_code="ST-H2")
    order_id = ctx["order"]["id"]
    schedule_run(
        order_id, station["id"],
        start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z",
        shots_planned=100,
    )
    res = api.create_forming_run(
        create_forming_run_payload(
            order_id, station["id"],
            planned_start="2026-05-02T10:30:00Z",
            planned_end="2026-05-02T11:30:00Z",
            shots_planned=100,
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_STATION_WINDOW_OVERLAP)


def _setup_two_order_station_scenario(api):
    """Shared setup for the safety-vs-temporal pair: an INDUSTRIAL order with
    a SCHEDULED run on a MEDICAL station 10:00-11:00, and a staged FOOD order
    whose tool is only INDUSTRIAL-graded."""
    lot_a = create_certified_lot(lot_code="LA")
    lot_b = create_certified_lot(
        lot_code="LB", cleanliness_grade_required="FOOD", unit_cost_per_kg=12.00
    )
    tool_a = create_tool_production(tool_code="TA", part_number="P-A", prototype_cost=1200.00)
    tool_b = create_tool_production(tool_code="TB", part_number="P-B", prototype_cost=1200.00)
    spec = create_stock_spec(spec_code="S-M", cleanliness_grade="MEDICAL", per_pack_cost=1.20)
    station = create_station(
        resource_code="ST-S", cleanliness_grade="MEDICAL", machine_rate_per_hour=60.00
    )

    order_a = create_order(tool_a, spec, order_code="OA", std_machine_rate_per_hour=60.00)
    reserve_virgin(order_a["id"], lot_a["id"], 5.900)
    stage_order(order_a["id"])
    run_a = schedule_run(
        order_a["id"], station["id"],
        start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z",
        shots_planned=50,
    )

    order_b = create_order(
        tool_b, spec, order_code="OB", cleanliness_grade="FOOD",
        std_machine_rate_per_hour=60.00,
    )
    reserve_virgin(order_b["id"], lot_b["id"], 5.900)
    stage_order(order_b["id"])
    return {"station": station, "order_b": order_b, "run_a": run_a}


def test_run_create_grade_incompatible_beats_overlap(api):
    """PRD §2.9: "When several rules could reject the same request, checks are
    evaluated in a fixed priority order, and the earliest failing check
    determines the error returned."
    PRD §2.9: "7. **Cleanliness compatibility** — grade-rank comparisons
    between order, spec, lot or batch certificate, tool, station, and booth
    (`ERR_GRADE_INCOMPATIBLE`)."
    PRD §2.9: "8. **Temporal rules** — window overlaps, the booth turnover
    buffer, and certificate time-validity at the current logical time
    (`ERR_STATION_WINDOW_OVERLAP`, `ERR_BOOTH_WINDOW_OVERLAP`,
    `ERR_BOOTH_BUFFER_VIOLATION`, `ERR_CERTIFICATE_INVALID`)."
    PRD §3.6: "Both the tool's `cleanliness_grade` and the station's
    `cleanliness_grade` must rank at least as high as the order's grade,
    otherwise `ERR_GRADE_INCOMPATIBLE`."

    The FOOD order's tool is INDUSTRIAL (safety failure) and the requested
    window also overlaps an existing SCHEDULED run (temporal failure); the
    safety error wins.

    Design: Difficulty/priority_pair_validation_conflict/run_create_safety_beats_temporal_priority
    """
    ctx = _setup_two_order_station_scenario(api)
    res = api.create_forming_run(
        create_forming_run_payload(
            ctx["order_b"]["id"], ctx["station"]["id"],
            planned_start="2026-05-02T10:30:00Z",
            planned_end="2026-05-02T11:30:00Z",
            shots_planned=50,
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_GRADE_INCOMPATIBLE)


def test_run_create_tool_grade_below_order_rejected_without_overlap(api):
    """PRD §3.6: "Both the tool's `cleanliness_grade` and the station's
    `cleanliness_grade` must rank at least as high as the order's grade,
    otherwise `ERR_GRADE_INCOMPATIBLE`."

    The safety gate on its own: at a non-overlapping window the FOOD order
    still cannot run on the INDUSTRIAL-graded tool.

    Design: Difficulty/priority_pair_validation_conflict/run_create_safety_beats_temporal_priority
    """
    ctx = _setup_two_order_station_scenario(api)
    res = api.create_forming_run(
        create_forming_run_payload(
            ctx["order_b"]["id"], ctx["station"]["id"],
            planned_start="2026-05-02T12:00:00Z",
            planned_end="2026-05-02T13:00:00Z",
            shots_planned=50,
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_GRADE_INCOMPATIBLE)
