"""Inspection recording, wall-thickness statistics, dispositions, booth
scheduling, and the shot conservation invariant (PRD §3.7, §3.6)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_quality_inspection,
    assert_shot_conservation,
    complete_run,
    create_booth,
    create_certified_lot,
    create_order,
    create_quality_inspection_payload,
    create_station,
    create_stock_spec,
    create_tool_production,
    disposition_inspection_ok,
    get_order,
    get_success_data,
    make_inspector_headers,
    record_inspection,
    reserve_virgin,
    schedule_run,
    setup_order_with_completed_run,
    setup_running_order,
    stage_order,
    INSPECTOR_1,
    INSPECTOR_2,
    validate_error,
    validate_paginated,
    validate_success,
)

_SCHEDULER = TEST_USERS["production_scheduler_headers"]
_ANY = TEST_USERS["any_headers"]


def test_wall_stats_per_measurement_rounding(api):
    """PRD §3.7: "First, each reading in `wall_measurements_mm` is
    individually rounded half-up to the nearest 0.001 mm. Then `min_wall_mm`
    is the smallest of those per-measurement-rounded readings, `avg_wall_mm`
    is the mean of the rounded readings itself rounded half-up to 0.001 mm,
    and `deviation_pct` is the difference between the order's
    `spec_nominal_wall_mm` and `min_wall_mm`, divided by
    `spec_nominal_wall_mm`, multiplied by 100, and rounded half-up to two
    decimal places."
    PRD §3.7: "Rounding after aggregation instead is non-conformant: a raw
    reading of 1.2305 mm against a `spec_min_wall_mm` of 1.231 must pass after
    per-measurement rounding (the rounded reading is 1.231, which meets the
    floor), whereas comparing the raw minimum would fail it."

    Readings [1.2305, 1.2400, 1.2500] round per-measurement to 1.231 / 1.240 /
    1.250: min 1.231, avg 1.240, deviation (1.300-1.231)/1.300*100 = 5.31.

    Design: Difficulty/combinatorial_formula/wall_thickness_per_measurement_rounding_order
    """
    ctx = setup_order_with_completed_run(
        lot_overrides={"lot_code": "LR", "resin_type": "HIPS", "unit_cost_per_kg": 8.00},
        tool_overrides={"tool_code": "TR", "part_number": "P-R", "prototype_cost": 1500.00},
        order_overrides={
            "order_code": "OR", "resin_type": "HIPS", "spec_min_wall_mm": 1.231,
        },
    )
    booth = create_booth(resource_code="B-R")
    res = api.create_quality_inspection(
        create_quality_inspection_payload(
            ctx["order"]["id"], booth["id"],
            forming_run_id=ctx["run"]["id"],
            inspection_type="FIRST_ARTICLE",
            scheduled_start="2026-05-02T11:00:00Z",
            scheduled_end="2026-05-02T11:30:00Z",
            wall_measurements_mm=[1.2305, 1.2400, 1.2500],
        ),
        make_inspector_headers(INSPECTOR_1),
    )
    insp = validate_success(res, 201)
    assert_quality_inspection(insp)
    assert insp["min_wall_mm"] == 1.231, (
        f"per-measurement rounding yields min 1.231, got {insp['min_wall_mm']}"
    )
    assert insp["avg_wall_mm"] == 1.240, (
        f"avg over rounded readings is 1.240, got {insp['avg_wall_mm']}"
    )
    assert insp["deviation_pct"] == 5.31, (
        f"deviation is 5.31, got {insp['deviation_pct']}"
    )


def test_pass_accepted_at_rounded_wall_boundary(api):
    """PRD §3.7: "Rounding after aggregation instead is non-conformant: a raw
    reading of 1.2305 mm against a `spec_min_wall_mm` of 1.231 must pass after
    per-measurement rounding (the rounded reading is 1.231, which meets the
    floor), whereas comparing the raw minimum would fail it."
    PRD §3.7: "`PASS` requires `min_wall_mm` to be at least the order's
    `spec_min_wall_mm`; passing an under-wall inspection is
    `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT`."

    Because per-measurement rounding lifts 1.2305 to 1.231, the PASS
    disposition is legal and releases the order's quality dimension.

    Design: Difficulty/combinatorial_formula/wall_thickness_per_measurement_rounding_order
    """
    ctx = setup_order_with_completed_run(
        lot_overrides={"resin_type": "HIPS"},
        order_overrides={"resin_type": "HIPS", "spec_min_wall_mm": 1.231},
    )
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        measurements=[1.2305, 1.2400, 1.2500],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z"),
    )
    disp = disposition_inspection_ok(insp["id"], "PASS")
    assert disp["status"] == "DISPOSITIONED", (
        "PASS must be accepted when the rounded minimum meets the floor"
    )
    order = get_order(ctx["order"]["id"])
    assert order["quality_status"] == "RELEASED"


def test_pass_at_exact_min_wall_boundary_accepted(api):
    """PRD §3.7: "`PASS` requires `min_wall_mm` to be at least the order's
    `spec_min_wall_mm`; passing an under-wall inspection is
    `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT`."

    min_wall_mm 1.230 exactly equals spec_min_wall_mm 1.230; the at-least
    rule admits PASS at the boundary.

    Design: Difficulty/boundary_precision_check/disposition_pass_at_exact_min_wall_boundary
    """
    ctx = setup_order_with_completed_run()  # spec_min 1.230, 10 shots completed
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        measurements=[1.2300, 1.2500],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T13:00:00Z", "2026-05-02T13:30:00Z"),
    )
    assert insp["min_wall_mm"] == 1.230
    disp = disposition_inspection_ok(insp["id"], "PASS")
    assert disp["status"] == "DISPOSITIONED", (
        "PASS at the exact spec_min boundary must be accepted (at-least is inclusive)"
    )


def test_scrap_at_exact_min_wall_boundary_rejected(api):
    """PRD §3.7: "`SCRAP` requires `min_wall_mm` strictly below
    `spec_min_wall_mm` (otherwise `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT`)
    and requires a positive `scrapped_qty` naming how many parts are
    condemned; `scrapped_qty` must also not exceed the order's current
    `shots_completed` (otherwise `ERR_INVALID_REQUEST`)."

    On readings whose rounded minimum equals spec_min, SCRAP contradicts the
    measurement.

    Design: Difficulty/boundary_precision_check/disposition_pass_at_exact_min_wall_boundary
    """
    ctx = setup_order_with_completed_run()
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        measurements=[1.2300, 1.2500],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T14:00:00Z", "2026-05-02T14:30:00Z"),
    )
    assert insp["min_wall_mm"] == 1.230
    res = api.disposition_inspection(
        insp["id"], {"disposition": "SCRAP", "scrapped_qty": 5},
        make_inspector_headers(INSPECTOR_2),
    )
    validate_error(res, ApiErrorId.ERR_DISPOSITION_CONTRADICTS_MEASUREMENT)


def test_rework_disposition_holds_both_dimensions(api):
    """PRD §3.7: "`REWORK` moves the order's `quality_status` `PENDING` →
    `REWORK_HOLD`; if the order's schedule is `RUNNING`, it is simultaneously
    forced to `ON_HOLD`."
    PRD §3.5: "The order is born with `schedule_status` `QUEUED` and
    `quality_status` `PENDING` — two independent dimensions that move
    separately"

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_rework_hold_loop
    """
    ctx = setup_order_with_completed_run(run_shots=50)
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z"),
    )
    disp = disposition_inspection_ok(insp["id"], "REWORK")
    assert disp["status"] == "DISPOSITIONED"

    order = get_order(ctx["order"]["id"])
    assert order["quality_status"] == "REWORK_HOLD", (
        f"quality dimension must move to REWORK_HOLD, got {order['quality_status']}"
    )
    assert order["schedule_status"] == "ON_HOLD", (
        f"schedule dimension must be forced to ON_HOLD, got {order['schedule_status']}"
    )


def test_resume_cycles_both_dimensions_back(api):
    """PRD §3.7: "The path back runs through resume (§3.6), which returns the
    quality dimension to `PENDING`."
    PRD §3.6: "A successful resume also clears a quality dimension held for
    rework — `quality_status` moves `REWORK_HOLD` → `PENDING` — and advances
    the order's `version`."

    Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_rework_hold_loop
    """
    ctx = setup_order_with_completed_run(run_shots=50)
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z"),
    )
    disposition_inspection_ok(insp["id"], "REWORK")
    held = get_order(ctx["order"]["id"])
    assert held["schedule_status"] == "ON_HOLD" and held["quality_status"] == "REWORK_HOLD"

    resumed = validate_success(api.resume_order(ctx["order"]["id"], _SCHEDULER), 200)
    assert resumed["schedule_status"] == "RUNNING", (
        f"resume must move the schedule dimension back to RUNNING, got {resumed['schedule_status']}"
    )
    order = get_order(ctx["order"]["id"])
    assert order["quality_status"] == "PENDING", (
        f"resume must clear REWORK_HOLD back to PENDING, got {order['quality_status']}"
    )


def test_scrap_disposition_moves_shots_between_counters(api):
    """PRD §3.7: "On success the order's `shots_completed` decreases by
    `scrapped_qty` and its `shots_scrapped` increases by the same amount,
    preserving the shot-conservation invariant."
    PRD §3.7: "`SCRAP` requires `min_wall_mm` strictly below
    `spec_min_wall_mm` (otherwise `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT`)
    and requires a positive `scrapped_qty` naming how many parts are
    condemned"

    Design: Difficulty/compensating_invariant/order_shot_complete_scrap_conservation
    """
    ctx = setup_order_with_completed_run(
        run_shots=60, run_scrap_kg=1.000,
        run_window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
    )
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        measurements=[1.100, 1.150],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T12:00:00Z", "2026-05-02T12:30:00Z"),
    )
    assert insp["min_wall_mm"] == 1.100  # strictly below spec_min 1.230

    disp = disposition_inspection_ok(insp["id"], "SCRAP", scrapped_qty=10)
    assert disp["status"] == "DISPOSITIONED"

    order = get_order(ctx["order"]["id"])
    assert order["shots_completed"] == 50, (
        f"60 completed minus 10 scrapped leaves 50, got {order['shots_completed']}"
    )
    assert order["shots_scrapped"] == 10, (
        f"shots_scrapped must increase by the condemned quantity, got {order['shots_scrapped']}"
    )


def test_shot_conservation_invariant_holds(api):
    """PRD §3.6: "One conservation invariant guards the shot counters: at all
    times, an order's `shots_completed` plus its `shots_scrapped` equals the
    sum of `shots_completed` over the order's `COMPLETED` forming runs, with
    integer-exact equality."
    PRD §3.6: "a `SCRAP` disposition (§3.7) moves quantity from
    `shots_completed` to `shots_scrapped` without changing either side's
    total."

    Design: Difficulty/compensating_invariant/order_shot_complete_scrap_conservation
    """
    ctx = setup_order_with_completed_run(
        run_shots=60, run_scrap_kg=1.000,
        run_window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
    )
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        measurements=[1.100, 1.150],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T12:00:00Z", "2026-05-02T12:30:00Z"),
    )
    disposition_inspection_ok(insp["id"], "SCRAP", scrapped_qty=10)

    order = get_order(ctx["order"]["id"])
    runs, _meta = validate_paginated(
        api.list_forming_runs(_ANY, params={"production_order_id": order["id"]})
    )
    completed_runs = [r for r in runs if r["status"] == "COMPLETED"]
    assert_shot_conservation(order, completed_runs)

    # The condemned shots must be re-run: nothing about SCRAP releases quality
    # or completes the schedule.
    assert order["schedule_status"] == "RUNNING"
    assert order["quality_status"] == "PENDING"


def test_disposition_pass_on_failing_walls_rejected(api):
    """PRD §3.7: "`PASS` requires `min_wall_mm` to be at least the order's
    `spec_min_wall_mm`; passing an under-wall inspection is
    `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT`."

    min_wall_mm 1.100 is below spec_min 1.230, so PASS contradicts the
    measurement.

    Design: Corner/validations/disposition_pass_on_failing_walls_rejected
    """
    ctx = setup_order_with_completed_run()
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        measurements=[1.100, 1.150],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z"),
    )
    res = api.disposition_inspection(
        insp["id"], {"disposition": "PASS"}, make_inspector_headers(INSPECTOR_2)
    )
    validate_error(res, ApiErrorId.ERR_DISPOSITION_CONTRADICTS_MEASUREMENT)


def test_sod_inspection_disposition_by_recorder_rejected(api):
    """PRD §3.7: "Disposition is deliberately segregated: the
    `QualityInspector` who dispositions an inspection must not be the one who
    recorded it — an `X-User-ID` matching `recorded_by_user_id` is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and the inspection must
    still be `RECORDED`, otherwise `ERR_INSPECTION_ALREADY_DISPOSITIONED`."
    PRD §3.7: "The recorder's `X-User-ID` is captured as
    `recorded_by_user_id`, and the inspection is born `RECORDED`."

    Design: Corner/rbac/sod_inspection_disposition_by_recorder_rejected
    """
    ctx = setup_order_with_completed_run()
    booth = create_booth()
    insp = record_inspection(
        ctx["order"]["id"], booth["id"],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T11:00:00Z", "2026-05-02T11:30:00Z"),
        recorder_id=INSPECTOR_1,
    )
    assert insp["recorded_by_user_id"] == INSPECTOR_1
    assert insp["status"] == "RECORDED"

    res = api.disposition_inspection(
        insp["id"], {"disposition": "PASS"}, make_inspector_headers(INSPECTOR_1)
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    disp = disposition_inspection_ok(insp["id"], "PASS", dispositioner_id=INSPECTOR_2)
    assert disp["status"] == "DISPOSITIONED"

    res3 = api.disposition_inspection(
        insp["id"], {"disposition": "PASS"}, make_inspector_headers(INSPECTOR_2)
    )
    validate_error(res3, ApiErrorId.ERR_INSPECTION_ALREADY_DISPOSITIONED)


def test_booth_window_overlap_rejected(api):
    """PRD §3.7: "An overlap with another inspection on the same booth that is
    still `RECORDED` — windows genuinely intersecting, adjacency alone being
    no conflict — is rejected with `ERR_BOOTH_WINDOW_OVERLAP`; inspections
    already `DISPOSITIONED` no longer occupy their booth."

    Both sessions are INDUSTRIAL-grade, so the turnover buffer plays no part;
    only the raw half-open overlap rule fires.

    Design: Corner/validations/booth_window_overlap_rejected
    """
    ctx = setup_order_with_completed_run()
    booth = create_booth()
    record_inspection(
        ctx["order"]["id"], booth["id"],
        run_id=ctx["run"]["id"],
        window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
    )
    res = api.create_quality_inspection(
        create_quality_inspection_payload(
            ctx["order"]["id"], booth["id"],
            forming_run_id=ctx["run"]["id"],
            inspection_type="FIRST_ARTICLE",
            scheduled_start="2026-05-02T10:30:00Z",
            scheduled_end="2026-05-02T11:30:00Z",
            wall_measurements_mm=[1.240, 1.250],
        ),
        make_inspector_headers(INSPECTOR_1),
    )
    validate_error(res, ApiErrorId.ERR_BOOTH_WINDOW_OVERLAP)


def _setup_booth_turnover_scenario(api):
    """An INDUSTRIAL order and a FOOD order, each RUNNING with one COMPLETED
    run on a MEDICAL station, and the INDUSTRIAL order's RECORDED inspection
    occupying a MEDICAL booth 10:00-11:00 (PRD §3.7 turnover setup)."""
    lot_i = create_certified_lot(lot_code="LI")
    lot_f = create_certified_lot(
        lot_code="LF", cleanliness_grade_required="FOOD", unit_cost_per_kg=12.00
    )
    tool_i = create_tool_production(tool_code="TI", part_number="P-I", prototype_cost=1200.00)
    tool_f = create_tool_production(
        tool_code="TF", part_number="P-F8", cleanliness_grade="FOOD",
        prototype_cost=1500.00, production_cost=9500.00, rated_lifetime_shots=95000,
    )
    spec = create_stock_spec(spec_code="S-M8", cleanliness_grade="MEDICAL", per_pack_cost=1.20)
    station = create_station(
        resource_code="ST-G", cleanliness_grade="MEDICAL", machine_rate_per_hour=60.00
    )
    booth = create_booth(resource_code="B-G", cleanliness_grade="MEDICAL")

    order_i = create_order(tool_i, spec, order_code="OI", std_machine_rate_per_hour=60.00)
    reserve_virgin(order_i["id"], lot_i["id"], 5.900)
    stage_order(order_i["id"])
    run_i = schedule_run(
        order_i["id"], station["id"],
        start="2026-05-02T08:00:00Z", end="2026-05-02T08:30:00Z",
    )
    complete_run(run_i["id"], 10, 0.000, actual_end="2026-05-02T08:30:00Z")

    order_f = create_order(
        tool_f, spec, order_code="OF8", cleanliness_grade="FOOD",
        std_machine_rate_per_hour=60.00,
    )
    reserve_virgin(order_f["id"], lot_f["id"], 5.900)
    stage_order(order_f["id"])
    run_f = schedule_run(
        order_f["id"], station["id"],
        start="2026-05-02T09:00:00Z", end="2026-05-02T09:30:00Z",
    )
    complete_run(run_f["id"], 10, 0.000, actual_end="2026-05-02T09:30:00Z")

    insp_i = record_inspection(
        order_i["id"], booth["id"], run_id=run_i["id"],
        window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
    )
    return {"booth": booth, "order_f": order_f, "run_f": run_f, "insp_i": insp_i}


def test_booth_buffer_15_minutes_rejected(api):
    """PRD §3.7: "On top of raw overlap, a turnover buffer protects grade
    transitions: when the earlier session's order is `INDUSTRIAL` grade and
    the later session's order is `FOOD` or `MEDICAL`, the later session must
    begin no earlier than 30 minutes after the earlier session's end. A
    tighter gap is rejected with `ERR_BOOTH_BUFFER_VIOLATION`; a gap of
    exactly 30 minutes is allowed."

    The FOOD session at 11:15 begins only 15 minutes after the INDUSTRIAL
    session ended at 11:00.

    Design: Difficulty/resource_temporal_overlap/booth_industrial_turnover_buffer
    """
    ctx = _setup_booth_turnover_scenario(api)
    res = api.create_quality_inspection(
        create_quality_inspection_payload(
            ctx["order_f"]["id"], ctx["booth"]["id"],
            forming_run_id=ctx["run_f"]["id"],
            inspection_type="FIRST_ARTICLE",
            scheduled_start="2026-05-02T11:15:00Z",
            scheduled_end="2026-05-02T11:45:00Z",
            wall_measurements_mm=[1.240, 1.250],
        ),
        make_inspector_headers(INSPECTOR_1),
    )
    validate_error(res, ApiErrorId.ERR_BOOTH_BUFFER_VIOLATION)


def test_booth_buffer_exactly_30_minutes_allowed(api):
    """PRD §3.7: "A tighter gap is rejected with
    `ERR_BOOTH_BUFFER_VIOLATION`; a gap of exactly 30 minutes is allowed."

    The FOOD session at 11:30 begins exactly 30 minutes after the INDUSTRIAL
    session ended at 11:00; the buffer boundary is inclusive.

    Design: Difficulty/resource_temporal_overlap/booth_industrial_turnover_buffer
    """
    ctx = _setup_booth_turnover_scenario(api)
    insp_f = validate_success(
        api.create_quality_inspection(
            create_quality_inspection_payload(
                ctx["order_f"]["id"], ctx["booth"]["id"],
                forming_run_id=ctx["run_f"]["id"],
                inspection_type="FIRST_ARTICLE",
                scheduled_start="2026-05-02T11:30:00Z",
                scheduled_end="2026-05-02T12:00:00Z",
                wall_measurements_mm=[1.240, 1.250],
            ),
            make_inspector_headers(INSPECTOR_1),
        ),
        201,
    )
    assert_quality_inspection(insp_f)
    assert insp_f["status"] == "RECORDED", (
        "a gap of exactly 30 minutes satisfies the turnover buffer"
    )
