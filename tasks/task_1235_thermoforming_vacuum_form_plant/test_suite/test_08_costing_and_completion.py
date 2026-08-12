"""Order costing variants and the completion cascade (PRD §3.5, §3.6, §3.3)."""
from test_helpers import (
    TEST_USERS,
    assert_production_order,
    complete_run,
    create_booth,
    create_certified_lot,
    create_order,
    create_station,
    create_stock_spec,
    create_tool_production,
    create_tool_prototype,
    disposition_inspection_ok,
    get_allocation,
    get_lot,
    get_order,
    get_success_data,
    record_inspection,
    reserve_virgin,
    schedule_run,
    setup_quality_released_order,
    setup_staged_order,
    stage_order,
    validate_success,
)

_ENGINEER = TEST_USERS["tooling_engineer_headers"]
_SCHEDULER = TEST_USERS["production_scheduler_headers"]


def test_provisional_cost_and_tooling_at_stage(api):
    """PRD §3.5: "The machine component is the ordered quantity times
    `std_cycle_time_s`, divided by 3600 to yield hours, times
    `std_machine_rate_per_hour`, rounded half-up to two decimal places."
    PRD §3.5: "The order's `provisional_cost` is the 250.00 setup fee plus the
    machine component, the material component, and the tooling charge, rounded
    half-up to two decimal places."
    PRD §3.3: "When the tool is in `PRODUCTION`, the charge is amortized: a
    per-shot rate is computed as `production_cost` divided by
    `rated_lifetime_shots`, rounded half-up to four decimal places, and the
    order's charge is that per-shot rate multiplied by the order's
    `ordered_qty`, rounded half-up to two decimal places."

    Plan pricing: 250.00 setup + (100 x 30s / 3600 x 60.00 = 50.00) machine +
    (5.900kg x 10.00 = 59.00) material + (0.1000 per shot x 100 = 10.00)
    tooling = 369.00.

    Design: Difficulty/dual_variant_calc/order_cost_provisional_vs_final_divergence
    """
    ctx = setup_staged_order(
        lot_overrides={"lot_code": "L-100"},
        tool_overrides={
            "tool_code": "T-100", "part_number": "P-100",
            "tool_type": "MATCHED_SET", "prototype_cost": 2000.00,
        },
        production_cost=10000.00,
        rated_lifetime_shots=100000,
        spec_overrides={"spec_code": "S-1", "per_pack_cost": 0.50},
        order_overrides={"order_code": "O-1", "std_machine_rate_per_hour": 60.00},
    )
    order = ctx["order"]
    assert order["schedule_status"] == "STAGED"
    assert order["tooling_charge"] == 10.00, (
        f"production tooling charge must be 10.00, got {order['tooling_charge']}"
    )
    assert order["provisional_cost"] == 369.00, (
        f"provisional cost of the plan must be 369.00, got {order['provisional_cost']}"
    )


def test_final_cost_after_completion_differs_from_provisional(api):
    """PRD §3.6: "Its machine component sums one term per `COMPLETED` run —
    the station's `machine_rate_per_hour` times the elapsed hours from
    `planned_start` to `actual_end`, each run's term rounded half-up to four
    decimal places — with the sum then rounded half-up to two decimal places."
    PRD §3.6: "The `final_cost` is the 250.00 setup fee plus these three
    components, rounded half-up to two decimal places."
    PRD §3.6: "The final cost prices actuality, and it legitimately differs
    from the provisional figure."
    PRD §3.6: "if the order's `shots_completed` has reached at least its
    `ordered_qty` and its `quality_status` is `RELEASED`, the order
    completes."

    Actuality pricing: the measured 1.0h window at the station's 60.00/h costs
    60.00 machine (vs the 50.00 standard-cycle plan), so final 379.00
    (250.00 + 60.00 + 59.00 + 10.00) diverges from provisional 369.00.

    Design: Difficulty/dual_variant_calc/order_cost_provisional_vs_final_divergence
    """
    ctx = setup_staged_order(
        lot_overrides={"lot_code": "L-100"},
        tool_overrides={
            "tool_code": "T-100", "part_number": "P-100",
            "tool_type": "MATCHED_SET", "prototype_cost": 2000.00,
        },
        production_cost=10000.00,
        rated_lifetime_shots=100000,
        spec_overrides={"spec_code": "S-1", "per_pack_cost": 0.50},
        order_overrides={"order_code": "O-1", "std_machine_rate_per_hour": 60.00},
    )
    order_id = ctx["order"]["id"]
    station = create_station(resource_code="ST-1", machine_rate_per_hour=60.00)
    booth = create_booth(resource_code="B-1")

    run = schedule_run(
        order_id, station["id"],
        start="2026-05-02T10:00:00Z", end="2026-05-02T11:00:00Z",
        cycle_time_s=28, shots_planned=100,
    )
    complete_run(run["id"], 100, 0.000, actual_end="2026-05-02T11:00:00Z")
    insp = record_inspection(
        order_id, booth["id"], inspection_type="FINAL",
        window=("2026-05-02T12:00:00Z", "2026-05-02T12:30:00Z"),
    )
    disposition_inspection_ok(insp["id"], "PASS")

    order = get_order(order_id)
    assert_production_order(order)
    assert order["schedule_status"] == "COMPLETED", (
        f"shots target met with quality RELEASED must complete the order, "
        f"got {order['schedule_status']}"
    )
    assert order["final_cost"] == 379.00, (
        f"final cost of actuality must be 379.00, got {order['final_cost']}"
    )
    assert order["provisional_cost"] == 369.00
    assert order["final_cost"] != order["provisional_cost"], (
        "the two variants legitimately differ: actuality priced 10.00 above the plan"
    )

    lot = get_lot(ctx["lot"]["id"])
    assert lot["available_kg"] == 4.100, (
        f"consumption of the 5.900kg allocation leaves 4.100kg, got {lot['available_kg']}"
    )


def test_prototype_tool_flat_tooling_charge(api):
    """PRD §3.3: "When the tool is in `PROTOTYPE`, the tooling charge is flat:
    the tool's full `prototype_cost` lands on the single order."
    PRD §3.5: "The order's `provisional_cost` is the 250.00 setup fee plus the
    machine component, the material component, and the tooling charge, rounded
    half-up to two decimal places."

    Prototype variant: 250.00 setup + 50.00 machine + 59.00 material +
    2000.00 flat tooling = 2359.00.

    Design: Difficulty/dual_variant_calc/tool_amortization_prototype_vs_production_variants
    """
    lot = create_certified_lot(lot_code="L-200", quantity_kg=20.000)
    tool_p = create_tool_prototype(
        tool_code="TP", part_number="P-100", prototype_cost=2000.00
    )
    spec = create_stock_spec(spec_code="S-2", per_pack_cost=0.50)
    order_p = create_order(
        tool_p, spec, order_code="OP", ordered_qty=100, std_machine_rate_per_hour=60.00
    )
    reserve_virgin(order_p["id"], lot["id"], 5.900)

    staged_p = stage_order(order_p["id"])
    assert staged_p["tooling_charge"] == 2000.00, (
        f"prototype tooling charge is the flat full prototype_cost, "
        f"got {staged_p['tooling_charge']}"
    )
    assert staged_p["provisional_cost"] == 2359.00, (
        f"prototype-variant provisional cost must be 2359.00, got {staged_p['provisional_cost']}"
    )


def test_production_tool_per_shot_tooling_charge(api):
    """PRD §3.3: "When the tool is in `PRODUCTION`, the charge is amortized: a
    per-shot rate is computed as `production_cost` divided by
    `rated_lifetime_shots`, rounded half-up to four decimal places, and the
    order's charge is that per-shot rate multiplied by the order's
    `ordered_qty`, rounded half-up to two decimal places."
    PRD §3.3: "The same order quantity therefore yields materially different
    charges depending on the tool's state — the prototype-to-production step
    changes unit economics."

    Production variant: per-shot round(10000.00/100000, 4) = 0.1000, times 100
    = 10.00 tooling; provisional 250.00 + 50.00 + 59.00 + 10.00 = 369.00 —
    1990.00 below the identical order on the PROTOTYPE tool.

    Design: Difficulty/dual_variant_calc/tool_amortization_prototype_vs_production_variants
    """
    lot = create_certified_lot(lot_code="L-200", quantity_kg=20.000)
    tool_q = create_tool_production(
        tool_code="TQ", part_number="P-100", prototype_cost=2000.00,
        production_cost=10000.00, rated_lifetime_shots=100000,
    )
    spec = create_stock_spec(spec_code="S-2", per_pack_cost=0.50)
    order_q = create_order(
        tool_q, spec, order_code="OQ", ordered_qty=100, std_machine_rate_per_hour=60.00,
    )
    reserve_virgin(order_q["id"], lot["id"], 5.900)

    staged_q = stage_order(order_q["id"])
    assert staged_q["tooling_charge"] == 10.00, (
        f"production tooling charge is per-shot amortized, got {staged_q['tooling_charge']}"
    )
    assert staged_q["provisional_cost"] == 369.00, (
        f"production-variant provisional cost must be 369.00, got {staged_q['provisional_cost']}"
    )


def test_run_complete_depth3_completion_cascade(api):
    """PRD §3.6: "if the order's `shots_completed` has reached at least its
    `ordered_qty` and its `quality_status` is `RELEASED`, the order
    completes."
    PRD §3.6: "Hop 1: every allocation of the order still `RESERVED` moves to
    `CONSUMED`. Hop 2: for each consumed virgin allocation the lot's
    `allocated_kg` decreases and its `consumed_kg` increases by the
    allocation's `qty_kg`; for each consumed regrind allocation the batch's
    `reserved_kg` decreases and its `consumed_kg` increases likewise. Hop 3:
    each touched lot recomputes `available_kg`, and a lot whose available mass
    reaches exactly zero moves `CERTIFIED` → `DEPLETED` per §3.1."

    The lot is sized exactly to the order's requirement (5.900kg), so the
    consumption hop zeroes available_kg and depletes the lot.

    Design: Difficulty/transitive_cascade/run_complete_depth3_completion_cascade
    """
    ctx = setup_quality_released_order(
        inspection_window=("2026-05-02T11:30:00Z", "2026-05-02T12:00:00Z"),
        run_window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
        run_shots=10,
        lot_overrides={"lot_code": "LC", "quantity_kg": 5.900},
        tool_overrides={"tool_code": "TC4", "part_number": "P-C4", "prototype_cost": 1500.00},
        production_cost=10000.00,
        rated_lifetime_shots=100000,
        spec_overrides={"spec_code": "S-C", "per_pack_cost": 0.50},
        order_overrides={"order_code": "OC", "std_machine_rate_per_hour": 60.00},
        station_overrides={"resource_code": "ST-C", "machine_rate_per_hour": 60.00},
    )
    order_id = ctx["order"]["id"]
    assert ctx["order"]["quality_status"] == "RELEASED"
    assert ctx["order"]["schedule_status"] == "RUNNING"

    run2 = schedule_run(
        order_id, ctx["station"]["id"],
        start="2026-05-02T11:00:00Z", end="2026-05-02T12:00:00Z",
        cycle_time_s=28, shots_planned=90,
    )
    complete_run(run2["id"], 90, 0.000, actual_end="2026-05-02T12:00:00Z")

    order = get_order(order_id)
    assert order["schedule_status"] == "COMPLETED", (
        f"hop 1: the order must complete, got {order['schedule_status']}"
    )
    alloc = get_allocation(ctx["allocation"]["id"])
    assert alloc["status"] == "CONSUMED", (
        f"hop 2: the allocation must be consumed, got {alloc['status']}"
    )
    lot = get_lot(ctx["lot"]["id"])
    assert lot["status"] == "DEPLETED", (
        f"hop 3: the zeroed-out lot must be DEPLETED, got {lot['status']}"
    )
    assert lot["available_kg"] == 0, f"available_kg must be exactly zero, got {lot['available_kg']}"
    assert lot["consumed_kg"] == 5.900


def test_run_complete_computes_final_cost(api):
    """PRD §3.6: "The order's `final_cost` is computed, the schedule moves to
    the terminal `COMPLETED` state, and the order's `version` advances."
    PRD §3.6: "The `final_cost` is the 250.00 setup fee plus these three
    components, rounded half-up to two decimal places."

    Two 1.0-hour completed runs at the station's 60.00/h give a 120.00
    machine component; with 59.00 consumed material and 10.00 amortized
    tooling the final cost is 250.00 + 120.00 + 59.00 + 10.00 = 439.00.

    Design: Difficulty/transitive_cascade/run_complete_depth3_completion_cascade
    """
    ctx = setup_quality_released_order(
        inspection_window=("2026-05-02T11:30:00Z", "2026-05-02T12:00:00Z"),
        run_window=("2026-05-02T10:00:00Z", "2026-05-02T11:00:00Z"),
        run_shots=10,
        lot_overrides={"lot_code": "LC", "quantity_kg": 5.900},
        tool_overrides={"tool_code": "TC4", "part_number": "P-C4", "prototype_cost": 1500.00},
        production_cost=10000.00,
        rated_lifetime_shots=100000,
        spec_overrides={"spec_code": "S-C", "per_pack_cost": 0.50},
        order_overrides={"order_code": "OC", "std_machine_rate_per_hour": 60.00},
        station_overrides={"resource_code": "ST-C", "machine_rate_per_hour": 60.00},
    )
    order_id = ctx["order"]["id"]
    run2 = schedule_run(
        order_id, ctx["station"]["id"],
        start="2026-05-02T11:00:00Z", end="2026-05-02T12:00:00Z",
        cycle_time_s=28, shots_planned=90,
    )
    complete_run(run2["id"], 90, 0.000, actual_end="2026-05-02T12:00:00Z")

    order = get_order(order_id)
    assert order["schedule_status"] == "COMPLETED"
    assert order["final_cost"] == 439.00, (
        f"final cost must be 439.00, got {order['final_cost']}"
    )


def test_tool_revise_cascade_holds_order(api):
    """PRD §3.3: "Revising moves `PRODUCTION` → `UNDER_REVISION` (legal only
    from `PRODUCTION`, else `ERR_INVALID_TOOL_TRANSITION`), increments
    `drawing_revision` by one, and advances the tool's `version` — and then it
    cascades two hops outward. First, every production order whose `tool_id`
    names this tool and whose `schedule_status` is `STAGED` or `RUNNING` is
    forced to `ON_HOLD`."

    Design: Difficulty/transitive_cascade/tool_revise_depth2_hold_review_cascade
    """
    ctx = setup_staged_order(
        lot_overrides={
            "lot_code": "LV", "resin_type": "PP", "gauge_mm": 2.000,
            "unit_cost_per_kg": 7.00,
        },
        tool_overrides={
            "tool_code": "TV", "part_number": "P-V",
            "tool_type": "TRIM_FIXTURE", "prototype_cost": 1500.00,
        },
        production_cost=8000.00,
        rated_lifetime_shots=80000,
        spec_overrides={"spec_code": "S-V", "per_pack_cost": 0.30},
        order_overrides={
            "order_code": "OV", "resin_type": "PP", "required_gauge_mm": 2.000,
            "spec_nominal_wall_mm": 1.500, "spec_min_wall_mm": 1.400,
            "std_cycle_time_s": 32, "std_machine_rate_per_hour": 50.00,
        },
    )
    assert ctx["order"]["schedule_status"] == "STAGED"

    tool = validate_success(api.revise_tool(ctx["tool"]["id"], _ENGINEER), 200)
    assert tool["status"] == "UNDER_REVISION"
    assert tool["drawing_revision"] == 2

    order = get_order(ctx["order"]["id"])
    assert order["schedule_status"] == "ON_HOLD", (
        f"hop 1: the STAGED order must be forced to ON_HOLD, got {order['schedule_status']}"
    )


def test_tool_revise_cascade_pushes_allocations_to_review(api):
    """PRD §3.3: "Second, for each order held by that first hop, every
    material allocation of the order in `RESERVED` moves to `REVIEW`,
    awaiting re-validation when the order resumes (§3.6)."

    Design: Difficulty/transitive_cascade/tool_revise_depth2_hold_review_cascade
    """
    ctx = setup_staged_order(
        lot_overrides={
            "lot_code": "LV", "resin_type": "PP", "gauge_mm": 2.000,
            "unit_cost_per_kg": 7.00,
        },
        tool_overrides={
            "tool_code": "TV", "part_number": "P-V",
            "tool_type": "TRIM_FIXTURE", "prototype_cost": 1500.00,
        },
        production_cost=8000.00,
        rated_lifetime_shots=80000,
        spec_overrides={"spec_code": "S-V", "per_pack_cost": 0.30},
        order_overrides={
            "order_code": "OV", "resin_type": "PP", "required_gauge_mm": 2.000,
            "spec_nominal_wall_mm": 1.500, "spec_min_wall_mm": 1.400,
            "std_cycle_time_s": 32, "std_machine_rate_per_hour": 50.00,
        },
    )
    validate_success(api.revise_tool(ctx["tool"]["id"], _ENGINEER), 200)

    order = get_order(ctx["order"]["id"])
    assert order["schedule_status"] == "ON_HOLD"
    alloc = get_allocation(ctx["allocation"]["id"])
    assert alloc["status"] == "REVIEW", (
        f"hop 2: the held order's RESERVED allocation must move to REVIEW, got {alloc['status']}"
    )
