"""The regrind loop: scrap intake, batch accumulation, segregated decisions,
and the blend cap (PRD §3.2, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_scrap_record,
    certify_scrap_into_batch,
    complete_run,
    create_batch,
    create_batch_decide_payload,
    create_certified_lot,
    create_material_allocation_payload,
    create_order,
    create_run_complete_payload,
    create_scrap_certify_payload,
    create_station,
    create_stock_spec,
    create_tool_production,
    decide_batch,
    find_scrap_record_for_run,
    get_batch,
    get_success_data,
    make_planner_headers,
    PLANNER_1,
    PLANNER_2,
    reserve_virgin,
    schedule_run,
    setup_certified_regrind_batch,
    setup_order_with_completed_run,
    setup_running_order,
    setup_staged_order,
    validate_error,
    validate_paginated,
    validate_success,
)

_PLANNER = TEST_USERS["materials_planner_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]
_ANY = TEST_USERS["any_headers"]


def test_batch_decide_before_target_rejected(api):
    """PRD §3.2: "Deciding a batch not in `PENDING_CERT` is rejected with
    `ERR_INVALID_BATCH_STATE`."

    The decider is a different planner than the creator, so segregation of
    duties is satisfied; only the state gate can fail.

    Design: Corner/state_machines/batch_decide_before_target_rejected
    """
    batch = create_batch(
        creator_id=PLANNER_1, batch_code="RB-E", resin_type="PETG",
        source_grade="INDUSTRIAL", target_kg=2.000,
    )
    assert batch["status"] == "ACCEPTING"
    res = api.decide_regrind_batch(
        batch["id"],
        create_batch_decide_payload("CERTIFIED", "INDUSTRIAL"),
        make_planner_headers(PLANNER_2),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_BATCH_STATE)


def test_scrap_certify_lifecycle_and_batch_auto_advance(api):
    """PRD §3.2: "With `decision` of `CERTIFY`, three preconditions apply: the
    scrap record must be `PENDING` (otherwise `ERR_INVALID_SCRAP_STATE`), the
    batch must be `ACCEPTING` (otherwise `ERR_INVALID_BATCH_STATE`), and the
    batch's `resin_type` must equal the scrap's `resin_type` (otherwise
    `ERR_RESIN_MISMATCH`)."
    PRD §3.2: "If that increase brings `accumulated_kg` to at least
    `target_kg`, the batch automatically advances `ACCEPTING` →
    `PENDING_CERT` and its `version` advances again."

    The re-certify attempt targets a second, still-ACCEPTING batch so only
    the scrap-state gate can fail.

    Design: Corner/cross_cutting_layers/scrap_certify_lifecycle_and_batch_auto_advance
    """
    donor = setup_order_with_completed_run(run_shots=10, run_scrap_kg=1.000)
    scrap = find_scrap_record_for_run(donor["run"]["id"])
    batch = create_batch(creator_id=PLANNER_1, batch_code="RB-CC2", target_kg=1.000)

    certified = validate_success(
        api.certify_scrap_record(
            scrap["id"], create_scrap_certify_payload(batch["id"], "CERTIFY"),
            make_planner_headers(PLANNER_1),
        ),
        200,
    )
    assert certified["status"] == "CERTIFIED"

    batch_after = get_batch(batch["id"])
    assert batch_after["status"] == "PENDING_CERT", (
        f"reaching the target must auto-advance the batch to PENDING_CERT, "
        f"got {batch_after['status']}"
    )
    assert batch_after["accumulated_kg"] == 1.000

    batch2 = create_batch(creator_id=PLANNER_1, batch_code="RB-CC2B", target_kg=5.000)
    res = api.certify_scrap_record(
        scrap["id"], create_scrap_certify_payload(batch2["id"], "CERTIFY"),
        make_planner_headers(PLANNER_1),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_SCRAP_STATE)


def test_sod_batch_decide_by_creator_rejected(api):
    """PRD §3.2: "If the decider's `X-User-ID` equals the batch's
    `created_by_user_id`, the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.2: "The batch moves to `CERTIFIED`, the supplied grade is stored as
    `certified_grade`, `max_blend_pct` is set to the blend cap for that
    certified grade, the decider is recorded as `decided_by_user_id`, and
    `version` advances."
    PRD §2.6: "an `INDUSTRIAL` order may draw at most 40 percent of its
    required material mass from regrind, a `FOOD` order at most 15 percent,
    and a `MEDICAL` order nothing at all"

    Design: Corner/rbac/sod_batch_decide_by_creator_rejected
    """
    donor = setup_order_with_completed_run(run_shots=10, run_scrap_kg=1.000)
    scrap = find_scrap_record_for_run(donor["run"]["id"])
    batch = create_batch(creator_id=PLANNER_1, batch_code="RB-SOD", target_kg=1.000)
    certify_scrap_into_batch(scrap["id"], batch["id"], planner_id=PLANNER_1)
    assert get_batch(batch["id"])["status"] == "PENDING_CERT"

    res = api.decide_regrind_batch(
        batch["id"],
        create_batch_decide_payload("CERTIFIED", "INDUSTRIAL"),
        make_planner_headers(PLANNER_1),
    )
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    decided = decide_batch(batch["id"], "CERTIFIED", "INDUSTRIAL", decider_id=PLANNER_2)
    assert decided["status"] == "CERTIFIED"
    assert decided["max_blend_pct"] == 0.40, (
        f"INDUSTRIAL blend cap is 40 percent, got {decided['max_blend_pct']}"
    )
    assert decided["decided_by_user_id"] == PLANNER_2


def test_run_complete_scrap_discovery_and_terminal_lockdown(api):
    """PRD §3.2: "The loop's intake point is the **scrap record**, which the
    system creates automatically when a forming run completes with a positive
    `scrap_weight_kg` (see §3.6)."
    PRD §3.6: "The run must be `SCHEDULED` (otherwise
    `ERR_INVALID_RUN_STATE`)"
    PRD §4: "the foreign-key reverse-reachability filters
    `production_order_id`, `lot_id`, `regrind_batch_id`, `station_id`,
    `forming_run_id`, and `booth_id` on their respective collections"

    Design: Corner/endpoints/run_complete_scrap_discovery_and_terminal_lockdown
    """
    ctx = setup_staged_order()
    station = create_station()
    run = schedule_run(ctx["order"]["id"], station["id"])

    completed = complete_run(run["id"], 10, 0.500, actual_end="2026-05-02T10:30:00Z")
    assert completed["status"] == "COMPLETED"

    scraps, meta = validate_paginated(
        api.list_scrap_records(_ANY, params={"forming_run_id": run["id"]})
    )
    assert len(scraps) == 1, f"exactly one scrap record must exist for the run, got {len(scraps)}"
    scrap = scraps[0]
    assert_scrap_record(scrap)
    assert scrap["status"] == "PENDING"
    assert scrap["weight_kg"] == 0.500, (
        f"weight_kg must equal the reported scrap mass, got {scrap['weight_kg']}"
    )
    assert scrap["resin_type"] == "PETG"

    res = api.complete_forming_run(
        run["id"], create_run_complete_payload(0, 0.000, "2026-05-02T10:35:00Z"), _SCHEDULER
    )
    validate_error(res, ApiErrorId.ERR_INVALID_RUN_STATE)


def test_regrind_blend_cap_food_cumulative_gate(api):
    """PRD §3.5: "And the blend cap binds cumulatively: the cap in kilograms
    is the order's `required_material_kg` multiplied by the blend cap for the
    order's grade — 40 percent for `INDUSTRIAL`, 15 percent for `FOOD`, zero
    for `MEDICAL` — rounded half-up to three decimal places, and the sum of
    `qty_kg` over all of the order's `RESERVED` regrind allocations including
    the new request must not exceed it, otherwise `ERR_BLEND_CAP_EXCEEDED`."

    FOOD cap on 5.900kg required material is round(5.900 x 0.15, 3) = 0.885kg;
    cumulative 0.800 passes, then +0.100 (cumulative 0.900) exceeds it.

    Design: Difficulty/combinatorial_formula/regrind_blend_cap_nested_min_gate
    """
    pack = setup_certified_regrind_batch(
        source_grade="FOOD", decided_grade="FOOD", target_kg=2.000, scrap_kg=2.500
    )
    batch = pack["batch"]
    assert batch["status"] == "CERTIFIED" and batch["accumulated_kg"] == 2.500

    lot_t = create_certified_lot(
        lot_code="LT", cleanliness_grade_required="FOOD", unit_cost_per_kg=12.00
    )
    tool_t = create_tool_production(
        tool_code="TT", part_number="P-F", tool_type="MATCHED_SET",
        cleanliness_grade="FOOD", prototype_cost=1800.00,
        production_cost=9500.00, rated_lifetime_shots=95000,
    )
    spec_t = create_stock_spec(spec_code="S-F", cleanliness_grade="FOOD", per_pack_cost=0.60)
    order_f = create_order(tool_t, spec_t, order_code="OF", cleanliness_grade="FOOD")
    reserve_virgin(order_f["id"], lot_t["id"], 5.900)

    res1 = api.create_material_allocation(
        create_material_allocation_payload(
            order_f["id"], source_type="REGRIND",
            regrind_batch_id=batch["id"], qty_kg=0.800,
        ),
        _SCHEDULER,
    )
    alloc_r = validate_success(res1, 201)
    assert alloc_r["status"] == "RESERVED", "cumulative 0.800 <= cap 0.885 must be accepted"

    res2 = api.create_material_allocation(
        create_material_allocation_payload(
            order_f["id"], source_type="REGRIND",
            regrind_batch_id=batch["id"], qty_kg=0.100,
        ),
        _SCHEDULER,
    )
    validate_error(res2, ApiErrorId.ERR_BLEND_CAP_EXCEEDED)


def test_regrind_blend_cap_reserved_tracking(api):
    """PRD §3.5: "and the sum of `qty_kg` over all of the order's `RESERVED`
    regrind allocations including the new request must not exceed it,
    otherwise `ERR_BLEND_CAP_EXCEEDED`."
    PRD §3.5: "Creating one adds `qty_kg` to the lot's `allocated_kg` or the
    batch's `reserved_kg` and advances the order's `version` by one."

    After the accepted 0.800kg and the rejected +0.100kg, the batch's
    reserved_kg reflects only the accepted allocation.

    Design: Difficulty/combinatorial_formula/regrind_blend_cap_nested_min_gate
    """
    pack = setup_certified_regrind_batch(
        source_grade="FOOD", decided_grade="FOOD", target_kg=2.000, scrap_kg=2.500
    )
    batch = pack["batch"]

    lot_t = create_certified_lot(
        lot_code="LT2", cleanliness_grade_required="FOOD", unit_cost_per_kg=12.00
    )
    tool_t = create_tool_production(
        tool_code="TT2", part_number="P-F2", tool_type="MATCHED_SET",
        cleanliness_grade="FOOD", prototype_cost=1800.00,
        production_cost=9500.00, rated_lifetime_shots=95000,
    )
    spec_t = create_stock_spec(spec_code="S-F2", cleanliness_grade="FOOD", per_pack_cost=0.60)
    order_f = create_order(tool_t, spec_t, order_code="OF2", cleanliness_grade="FOOD")
    reserve_virgin(order_f["id"], lot_t["id"], 5.900)

    validate_success(
        api.create_material_allocation(
            create_material_allocation_payload(
                order_f["id"], source_type="REGRIND",
                regrind_batch_id=batch["id"], qty_kg=0.800,
            ),
            _SCHEDULER,
        ),
        201,
    )
    validate_error(
        api.create_material_allocation(
            create_material_allocation_payload(
                order_f["id"], source_type="REGRIND",
                regrind_batch_id=batch["id"], qty_kg=0.100,
            ),
            _SCHEDULER,
        ),
        ApiErrorId.ERR_BLEND_CAP_EXCEEDED,
    )

    batch_after = get_batch(batch["id"])
    assert batch_after["reserved_kg"] == 0.800, (
        f"reserved_kg must track only the accepted allocation, got {batch_after['reserved_kg']}"
    )


def test_regrind_blend_at_exact_cap_accepted(api):
    """PRD §3.5: "And the blend cap binds cumulatively: the cap in kilograms
    is the order's `required_material_kg` multiplied by the blend cap for the
    order's grade — 40 percent for `INDUSTRIAL`, 15 percent for `FOOD`, zero
    for `MEDICAL` — rounded half-up to three decimal places, and the sum of
    `qty_kg` over all of the order's `RESERVED` regrind allocations including
    the new request must not exceed it, otherwise `ERR_BLEND_CAP_EXCEEDED`."

    INDUSTRIAL cap on 5.900kg required material is round(5.900 x 0.40, 3) =
    2.360kg; an exactly-at-cap allocation is accepted (the rule is
    must-not-exceed).

    Design: Difficulty/boundary_precision_check/regrind_blend_at_exact_cap_boundary
    """
    pack = setup_certified_regrind_batch(
        source_grade="INDUSTRIAL", decided_grade="INDUSTRIAL",
        target_kg=2.000, scrap_kg=2.500,
    )
    batch = pack["batch"]
    donor = pack["donor"]

    order_cap = create_order(donor["tool"], donor["spec"], order_code="OCAP")
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order_cap["id"], source_type="REGRIND",
            regrind_batch_id=batch["id"], qty_kg=2.360,
        ),
        _SCHEDULER,
    )
    alloc = validate_success(res, 201)
    assert alloc["status"] == "RESERVED", "exactly-at-cap allocation must be accepted"
    assert get_batch(batch["id"])["reserved_kg"] == 2.360


def test_regrind_blend_one_gram_over_cap_rejected(api):
    """PRD §3.5: "the sum of `qty_kg` over all of the order's `RESERVED`
    regrind allocations including the new request must not exceed it,
    otherwise `ERR_BLEND_CAP_EXCEEDED`."

    With 2.360kg already reserved against the 2.360kg cap, one more gram
    (cumulative 2.361kg) exceeds the cap.

    Design: Difficulty/boundary_precision_check/regrind_blend_at_exact_cap_boundary
    """
    pack = setup_certified_regrind_batch(
        source_grade="INDUSTRIAL", decided_grade="INDUSTRIAL",
        target_kg=2.000, scrap_kg=2.500,
    )
    batch = pack["batch"]
    donor = pack["donor"]

    order_cap = create_order(donor["tool"], donor["spec"], order_code="OCAP2")
    get_success_data(
        api.create_material_allocation(
            create_material_allocation_payload(
                order_cap["id"], source_type="REGRIND",
                regrind_batch_id=batch["id"], qty_kg=2.360,
            ),
            _SCHEDULER,
        )
    )
    res = api.create_material_allocation(
        create_material_allocation_payload(
            order_cap["id"], source_type="REGRIND",
            regrind_batch_id=batch["id"], qty_kg=0.001,
        ),
        _SCHEDULER,
    )
    validate_error(res, ApiErrorId.ERR_BLEND_CAP_EXCEEDED)
    assert get_batch(batch["id"])["reserved_kg"] == 2.360, (
        "the rejected allocation must not change reserved_kg"
    )
