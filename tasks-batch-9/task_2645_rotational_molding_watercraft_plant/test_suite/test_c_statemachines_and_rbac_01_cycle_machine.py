"""Cycle, order and mould state machines: transitions, preconditions and traps.

PRD.md section 3.5 gives the moulding cycle five states and seven edges; this
module walks the manual spine end to end, probes the preconditions that guard
the oven start, checks the side effects that start leaves behind, and proves
that the wrong trigger, a repeated trigger and a terminal row are all refused.
Every expectation here is quoted from PRD.md in the test's own docstring.
"""

from test_helpers import (
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    Q_WARPAGE,
    abort_payload,
    assert_decimal_equals,
    assert_instant_equals,
    assert_resin_ledger_conserved,
    cancel_order_payload,
    complete_service_payload,
    cooling_bay_payload,
    create_customer,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    create_technician,
    demold_payload,
    enter_cooling_payload,
    get_success_data,
    inspect_payload,
    mark_down_payload,
    mold_payload,
    molding_cycle_payload,
    outfit_payload,
    oven_station_payload,
    production_order_version,
    release_charge_payload,
    release_storage_payload,
    reserve_charge,
    resin_charge_payload,
    resin_lot_version,
    retire_mold_payload,
    run_cycle_to_demold,
    schedule_cycle,
    service_hold_payload,
    set_clock,
    setup_scheduled_cycle,
    shipment_payload,
    start_oven_payload,
    suspend_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

SINGLE_CAVITY_MODEL = {"nominal_charge_kg": 24.0}
SINGLE_CAVITY_MOLD = {"cavity_count": 1, "nominal_charge_kg": 24.0}


def test_cycle_spine_scheduled_to_oven_running_to_cooling_to_demolded(api):
    """The four manual cycle states are reached in order and each stamps its own instant.

    PRD.md section 3.5: "A cycle addressed in the wrong state is refused with
    `ERR_CYCLE_INVALID_STATE` (HTTP 409): `SCHEDULED` is required to start the
    oven, `OVEN_RUNNING` to enter cooling, `COOLING` to demould, and
    `SCHEDULED`, `OVEN_RUNNING` or `COOLING` to abort."
    PRD.md section 3.5: "On success the cycle moves `SCHEDULED` to
    `OVEN_RUNNING` and `actual_oven_start_at` is recorded from the logical
    clock."
    PRD.md section 3.5: "The cycle moves `OVEN_RUNNING` to `COOLING`,
    `actual_oven_end_at` is recorded from the logical clock, and
    `actual_oven_minutes` is recomputed as the floored whole minutes between
    `actual_oven_start_at` and `actual_oven_end_at`."
    PRD.md section 3.5: "The cycle moves `COOLING` to `DEMOLDED`,
    `actual_cooling_end_at` is recorded and `actual_cooling_minutes`
    recomputed by flooring, and `provisional_warpage_index` is computed."
    PRD.md section 3.4: "`status` is `SCHEDULED`, `charged_mass_kg` is 0.000,
    `operator_technician_id` is the acting identifier, and the order moves
    `READY_TO_SCHEDULE` to `IN_PRODUCTION` on the first accepted cycle."
    PRD.md section 2.4: "`version` is an integer that starts at 1 when the row
    is created and increments by exactly 1 on every persisted mutation,
    including mutations that occur as cascade side effects of a request aimed
    at a different resource."

    Design: Corner/state_machines/sm_valid_transition_cycle_spine_scheduled_oven_running_cooling_demolded
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    lot = create_resin_lot(received_kg=500.0)
    order = create_production_order(ctx, ordered_qty=1)

    created = validate_success(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(order["id"]),
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert created["status"] == "SCHEDULED", "a new cycle starts SCHEDULED"
    assert_instant_equals(
        created["oven_end_at"], "2026-08-01T10:00:00Z", "oven_end_at projection"
    )
    assert_instant_equals(
        created["cooling_window_end_at"],
        "2026-08-01T10:30:00Z",
        "cooling_window_end_at projection",
    )
    cycle_id = created["id"]
    assert api.read_entity("get_production_order", order["id"], ctx["admin_headers"])[
        "status"
    ] == "IN_PRODUCTION", "the first accepted cycle moves the order to IN_PRODUCTION"

    get_success_data(
        api.create_resin_charge(
            resin_charge_payload(
                cycle_id, lot["id"], resin_lot_version(lot["id"]), charge_kg=24.0
            ),
            ctx["resin_tech_headers"],
        )
    )

    set_clock("2026-08-01T09:00:00Z")
    running = validate_success(
        api.start_oven(
            cycle_id, start_oven_payload("2026-08-01T09:00:00Z"), ctx["operator_headers"]
        )
    )
    assert running["status"] == "OVEN_RUNNING", "start-oven leaves the cycle OVEN_RUNNING"
    assert_instant_equals(
        running["actual_oven_start_at"], "2026-08-01T09:00:00Z", "actual_oven_start_at"
    )

    set_clock("2026-08-01T10:00:00Z")
    cooling = validate_success(
        api.enter_cooling(
            cycle_id,
            enter_cooling_payload("2026-08-01T10:00:00Z"),
            ctx["operator_headers"],
        )
    )
    assert cooling["status"] == "COOLING", "enter-cooling leaves the cycle COOLING"
    assert_instant_equals(
        cooling["actual_oven_end_at"], "2026-08-01T10:00:00Z", "actual_oven_end_at"
    )
    assert cooling["actual_oven_minutes"] == 60, "09:00 to 10:00 floors to 60 minutes"

    set_clock("2026-08-01T10:35:00Z")
    demolded = validate_success(
        api.demold(
            cycle_id, demold_payload("2026-08-01T10:35:00Z"), ctx["operator_headers"]
        )
    )
    assert demolded["status"] == "DEMOLDED", "demould leaves the cycle DEMOLDED"
    assert_instant_equals(
        demolded["actual_cooling_end_at"], "2026-08-01T10:35:00Z", "actual_cooling_end_at"
    )
    assert demolded["actual_cooling_minutes"] == 35, "10:00 to 10:35 floors to 35 minutes"
    assert demolded["abort_reason"] is None, "a demoulded cycle carries no abort_reason"
    assert_decimal_equals(
        demolded["provisional_warpage_index"], "0.000", Q_WARPAGE, "provisional index"
    )
    assert_instant_equals(
        demolded["oven_end_at"], "2026-08-01T10:00:00Z", "oven_end_at is still projected"
    )
    assert_instant_equals(
        demolded["cooling_window_end_at"],
        "2026-08-01T10:30:00Z",
        "cooling_window_end_at is still projected",
    )
    assert demolded["version"] == 5, (
        "one bump each for create, the charge roll-up, start-oven, enter-cooling "
        "and demould"
    )
    assert api.read_entity("get_production_order", order["id"], ctx["admin_headers"])[
        "status"
    ] == "IN_PRODUCTION", "the order stays IN_PRODUCTION after one of one hull"


def test_start_oven_preconditions_each_surface_their_own_error(api):
    """Identity, suspension and charge-mass violations each surface a distinct refusal.

    PRD.md section 3.5: "The cycle machine has five states and seven edges, and
    every manual edge is driven by the cycle's own `operator_technician_id` — a
    different `MoldingOperator` presenting a different `X-User-ID` is refused
    with `ERR_ROLE_IDENTITY_MISMATCH`, and a suspended operator with
    `ERR_TECHNICIAN_SUSPENDED`."
    PRD.md section 3.5: "The **charge mass tolerance** test compares the
    cycle's `charged_mass_kg` against the tool's `nominal_charge_kg` — which is
    the model's `nominal_charge_kg` multiplied by the tool's `cavity_count` —
    as an absolute percentage deviation: the absolute difference divided by the
    tool's `nominal_charge_kg`, times 100, rounded to two decimals, must be at
    most the model's `charge_tolerance_pct`."
    PRD.md section 3.5: "A deviation outside tolerance is
    `ERR_CHARGE_MASS_OUT_OF_TOLERANCE` (HTTP 422)."
    PRD.md section 3.5: "at least one charge on the cycle must be in `status`
    `RESERVED`, otherwise `ERR_RESIN_INSUFFICIENT`"
    PRD.md section 2.7: "Each endpoint evaluates its applicable checks in a
    fixed ascending priority order and returns on the first failure it finds;
    no endpoint reports two errors, and no later check runs after an earlier
    one has failed."
    PRD.md section 3.2: "The lot's `available_kg` falls and its `reserved_kg`
    rises by `charge_kg`, preserving the invariant that the rounded sum of
    `available_kg`, `reserved_kg` and `consumed_kg` equals `received_kg`"

    Design: Corner/state_machines/sm_precondition_start_oven_identity_suspension_missing_charge_and_mass_tolerance
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    second_operator = create_technician("MOLDING_OPERATOR")
    lot = create_resin_lot(received_kg=500.0)
    order = create_production_order(ctx, ordered_qty=3)

    cycle_a = schedule_cycle(ctx, order, oven_start_at="2026-08-01T09:00:00Z")
    cycle_b = schedule_cycle(ctx, order, oven_start_at="2026-08-01T11:00:00Z")
    cycle_c = schedule_cycle(ctx, order, oven_start_at="2026-08-01T13:00:00Z")
    reserve_charge(ctx, cycle_a, lot, charge_kg=24.0, regrind_kg=2.4)
    reserve_charge(ctx, cycle_c, lot, charge_kg=20.0, regrind_kg=2.0)

    set_clock("2026-08-01T09:00:00Z")
    payload = start_oven_payload("2026-08-01T09:00:00Z")

    validate_error(
        api.start_oven(cycle_a["id"], payload, second_operator["headers"]),
        ApiErrorId.ROLE_IDENTITY_MISMATCH,
    )

    get_success_data(
        api.suspend_technician(
            ctx["molding_operator_id"],
            suspend_payload("certification lapse"),
            ctx["admin_headers"],
        )
    )
    validate_error(
        api.start_oven(cycle_a["id"], payload, ctx["operator_headers"]),
        ApiErrorId.TECHNICIAN_SUSPENDED,
    )
    reinstated = get_success_data(
        api.reinstate_technician(ctx["molding_operator_id"], ctx["admin_headers"])
    )
    assert reinstated["status"] == "ACTIVE", "reinstating restores the ACTIVE status"
    assert reinstated["version"] == 3, "one bump each for create, suspend and reinstate"

    # A cycle with no reserved charge has charged_mass_kg 0.000, which also sits
    # outside the mass tolerance, and PRD.md section 2.7 does not settle which of
    # the two bands reports first; either refusal is faithful, and neither writes.
    validate_error_is_one_of(
        api.start_oven(cycle_b["id"], payload, ctx["operator_headers"]),
        [ApiErrorId.RESIN_INSUFFICIENT, ApiErrorId.CHARGE_MASS_OUT_OF_TOLERANCE],
    )

    validate_error(
        api.start_oven(cycle_c["id"], payload, ctx["operator_headers"]),
        ApiErrorId.CHARGE_MASS_OUT_OF_TOLERANCE,
    )

    started = validate_success(
        api.start_oven(cycle_a["id"], payload, ctx["operator_headers"])
    )
    assert started["status"] == "OVEN_RUNNING", (
        "the correctly charged cycle driven by its own reinstated operator starts"
    )

    refused = api.read_entity("get_molding_cycle", cycle_b["id"], ctx["admin_headers"])
    assert refused["status"] == "SCHEDULED", "a refused start leaves the cycle SCHEDULED"
    assert refused["actual_oven_start_at"] is None, "a refused start stamps nothing"

    final_lot = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert_decimal_equals(final_lot["available_kg"], "456.000", Q_MASS, "available_kg")
    assert_decimal_equals(final_lot["reserved_kg"], "20.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(final_lot["consumed_kg"], "24.000", Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(final_lot)


def test_start_oven_moves_reserved_mass_to_consumed_and_leaves_available_alone(api):
    """Consumption reshapes the lot ledger without touching available_kg or its sum.

    PRD.md section 3.5: "Every `RESERVED` charge on the cycle becomes
    `CONSUMED`, moving `charge_kg` from its lot's `reserved_kg` to its lot's
    `consumed_kg` while `available_kg` is untouched; any such lot whose
    `available_kg` already stands at exactly 0.000 while `AVAILABLE` becomes
    `DEPLETED`."
    PRD.md section 3.5: "The tool moves `AVAILABLE` to `IN_CYCLE`."
    PRD.md section 3.5: "every lot referenced by those charges must still be
    `AVAILABLE`, otherwise `ERR_RESIN_LOT_NOT_AVAILABLE`"
    PRD.md section 3.2: "a lot whose `available_kg` reaches exactly 0.000 moves
    `AVAILABLE` to `DEPLETED`."
    PRD.md section 3.5: "The tool moves `IN_CYCLE` to `AVAILABLE` and its
    `cycles_since_service` is incremented by 1 — only a completed demould wears
    a tool; an abort never does."
    PRD.md section 3.4: "the order moves `READY_TO_SCHEDULE` to
    `IN_PRODUCTION` on the first accepted cycle."
    PRD.md section 3.5: "The order moves `READY_TO_SCHEDULE` to
    `IN_PRODUCTION` if it is not already there."

    Design: Corner/state_machines/sm_side_effects_start_oven_consumes_reserved_mass_locks_the_tool_and_leaves_available_alone
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    big = create_resin_lot(received_kg=500.0)
    tight = create_resin_lot(received_kg=24.0)
    order = create_production_order(ctx, ordered_qty=2)

    cycle_1 = schedule_cycle(ctx, order, oven_start_at="2026-08-01T09:00:00Z")
    cycle_2 = schedule_cycle(ctx, order, oven_start_at="2026-08-01T11:00:00Z")
    charge_1 = reserve_charge(ctx, cycle_1, big, charge_kg=24.0, regrind_kg=2.4)
    charge_2 = reserve_charge(ctx, cycle_2, tight, charge_kg=24.0, regrind_kg=2.4)

    drained = api.read_entity("get_resin_lot", tight["id"], ctx["admin_headers"])
    assert_decimal_equals(drained["available_kg"], "0.000", Q_MASS, "drained available_kg")
    assert_decimal_equals(drained["reserved_kg"], "24.000", Q_MASS, "drained reserved_kg")
    assert_decimal_equals(drained["consumed_kg"], "0.000", Q_MASS, "drained consumed_kg")
    assert drained["status"] == "DEPLETED", (
        "reserving the last kilogram is what depletes the lot"
    )

    set_clock("2026-08-01T09:00:00Z")
    payload = start_oven_payload("2026-08-01T09:00:00Z")

    before_mold = api.read_entity("get_mold", ctx["mold_id"], ctx["admin_headers"])
    assert before_mold["status"] == "AVAILABLE", (
        "the tool is still AVAILABLE, so the refusal below cannot be a tool refusal"
    )
    validate_error(
        api.start_oven(cycle_2["id"], payload, ctx["operator_headers"]),
        ApiErrorId.RESIN_LOT_NOT_AVAILABLE,
    )

    started = validate_success(
        api.start_oven(cycle_1["id"], payload, ctx["operator_headers"])
    )
    assert started["status"] == "OVEN_RUNNING", "the well-supplied cycle starts"
    assert_instant_equals(
        started["actual_oven_start_at"], "2026-08-01T09:00:00Z", "actual_oven_start_at"
    )
    assert started["version"] == 3, (
        "one bump each for create, the charge roll-up and start-oven"
    )

    after_big = api.read_entity("get_resin_lot", big["id"], ctx["admin_headers"])
    assert_decimal_equals(after_big["available_kg"], "476.000", Q_MASS, "available_kg")
    assert_decimal_equals(after_big["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(after_big["consumed_kg"], "24.000", Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(after_big)
    assert after_big["status"] == "AVAILABLE", (
        "available_kg never moved, so the lot is not depleted"
    )

    consumed = api.read_entity("get_resin_charge", charge_1["id"], ctx["admin_headers"])
    assert consumed["status"] == "CONSUMED", "the started cycle's charge is consumed"
    assert consumed["released_reason"] is None, "a consumed charge was never released"
    assert consumed["version"] == 2, "one bump each for reserve and consume"

    untouched = api.read_entity("get_resin_charge", charge_2["id"], ctx["admin_headers"])
    assert untouched["status"] == "RESERVED", "the refused start consumed nothing"
    assert untouched["version"] == 1, "a refused start writes no version bump"

    after_mold = api.read_entity("get_mold", ctx["mold_id"], ctx["admin_headers"])
    assert after_mold["status"] == "IN_CYCLE", "the tool is locked for the oven leg"
    assert after_mold["version"] == 2, "one bump each for create and the lock"
    assert after_mold["cycles_since_service"] == 0, (
        "the service counter advances at demould, not at oven start"
    )

    after_order = api.read_entity(
        "get_production_order", order["id"], ctx["admin_headers"]
    )
    assert after_order["status"] == "IN_PRODUCTION", "the order is already in production"
    assert after_order["version"] == 4, (
        "one bump each for create, release and the two cycle bookings; the "
        "already-satisfied IN_PRODUCTION move bumps nothing"
    )


def test_invalid_triggers_are_refused_on_cycle_hull_and_order_machines(api):
    """A trigger aimed at the wrong state is refused and writes nothing on three machines.

    PRD.md section 3.5: "A cycle addressed in the wrong state is refused with
    `ERR_CYCLE_INVALID_STATE` (HTTP 409): `SCHEDULED` is required to start the
    oven, `OVEN_RUNNING` to enter cooling, `COOLING` to demould, and
    `SCHEDULED`, `OVEN_RUNNING` or `COOLING` to abort."
    PRD.md section 3.5: "`DEMOLDED` and `ABORTED` are both terminal."
    PRD.md section 3.6: "Trimming is legal from `build_status` `DEMOLDED` or
    `REWORK` and moves the hull to `TRIMMED`; any other build state is
    `ERR_UNIT_INVALID_BUILD_STATE` (HTTP 409)."
    PRD.md section 3.6: "`AssemblyTechnician` then **outfits** the hull,
    supplying `hardware_kit_serial`; this requires `build_status` `TRIMMED`"
    PRD.md section 3.6: "Inspection requires `build_status` `OUTFITTED` (a
    first inspection) or `SELLABLE` (a re-inspection), requires
    `logistics_status` `UNALLOCATED`, requires both the `WALL_GAUGE` and
    `IMPACT_RIG` certifications, and requires at least six numeric measurements
    each strictly greater than 0.000 in `wall_thickness_points`, otherwise
    `ERR_INSUFFICIENT_MEASUREMENTS` (HTTP 422)."
    PRD.md section 3.7: "**Releasing storage** requires `logistics_status`
    `STORED` and a `release_reason`"
    PRD.md section 3.4: "The order's `status` must be `READY_TO_SCHEDULE` or
    `IN_PRODUCTION`; a `DRAFT`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`,
    `COMPLETE` or `CANCELLED` order cannot take a new cycle and is refused with
    `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409)."
    PRD.md section 2.7: "Each endpoint evaluates its applicable checks in a
    fixed ascending priority order and returns on the first failure it finds"

    Design: Corner/state_machines/sm_invalid_triggers_rejected_from_scheduled_cycle_demolded_unit_and_draft_order
    """
    ctx = setup_scheduled_cycle(
        model_overrides=SINGLE_CAVITY_MODEL,
        mold_overrides=SINGLE_CAVITY_MOLD,
        order_overrides={"ordered_qty": 2},
        charge_overrides={"charge_kg": 24.0},
    )
    run_cycle_to_demold(ctx)
    done_cycle_id = ctx["molding_cycle_id"]
    unit = ctx["finished_units"][0]

    open_cycle = schedule_cycle(
        ctx, ctx["production_order"], oven_start_at="2026-08-01T13:00:00Z"
    )
    reserve_charge(ctx, open_cycle, ctx["resin_lot"], charge_kg=24.0)

    draft_order = create_production_order(ctx, release=False, ordered_qty=1)
    assert draft_order["status"] == "DRAFT", "the second order is left unreleased"

    validate_error(
        api.enter_cooling(
            open_cycle["id"],
            enter_cooling_payload("2026-08-01T13:00:00Z"),
            ctx["operator_headers"],
        ),
        ApiErrorId.CYCLE_INVALID_STATE,
    )
    validate_error(
        api.demold(
            open_cycle["id"],
            demold_payload("2026-08-01T13:00:00Z"),
            ctx["operator_headers"],
        ),
        ApiErrorId.CYCLE_INVALID_STATE,
    )
    validate_error(
        api.start_oven(
            done_cycle_id,
            start_oven_payload("2026-08-01T10:35:00Z"),
            ctx["operator_headers"],
        ),
        ApiErrorId.CYCLE_INVALID_STATE,
    )

    validate_error(
        api.outfit_finished_unit(
            unit["id"], outfit_payload("HK-INV-0001"), ctx["assembly_headers"]
        ),
        ApiErrorId.UNIT_INVALID_BUILD_STATE,
    )
    validate_error(
        api.inspect_finished_unit(unit["id"], inspect_payload(), ctx["inspector_headers"]),
        ApiErrorId.UNIT_INVALID_BUILD_STATE,
    )
    validate_error(
        api.release_storage(
            unit["id"],
            release_storage_payload("probe on an unstored hull"),
            ctx["planner_headers"],
        ),
        ApiErrorId.UNIT_INVALID_LOGISTICS_STATE,
    )

    validate_error(
        api.create_molding_cycle(
            molding_cycle_payload(
                draft_order["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(draft_order["id"]),
                arm_index=2,
                oven_start_at="2026-08-02T09:00:00Z",
            ),
            ctx["operator_headers"],
        ),
        ApiErrorId.ORDER_NOT_SCHEDULABLE,
    )

    still_open = api.read_entity(
        "get_molding_cycle", open_cycle["id"], ctx["admin_headers"]
    )
    assert still_open["status"] == "SCHEDULED", "two refusals left the cycle SCHEDULED"
    assert still_open["actual_oven_end_at"] is None, "no refused trigger stamped a time"
    assert still_open["version"] == 2, "one bump each for create and the charge roll-up"

    still_demolded = api.read_entity("get_finished_unit", unit["id"], ctx["admin_headers"])
    assert still_demolded["build_status"] == "DEMOLDED", "the build axis did not move"
    assert still_demolded["logistics_status"] == "UNALLOCATED", "nor the logistics axis"
    assert still_demolded["version"] == 1, "three refusals bumped nothing"
    assert still_demolded["hardware_kit_serial"] is None, "no kit serial was recorded"
    assert still_demolded["wall_thickness_points"] == [], "no measurements were stored"
    assert still_demolded["inspection_verdict"] == "PENDING", "the verdict is untouched"

    rows, meta = validate_paginated(
        api.list_molding_cycles(
            {"production_order_id": draft_order["id"]}, ctx["admin_headers"]
        )
    )
    assert meta["total_count"] == 0, "a refused booking writes no cycle row"
    assert rows == [], "a refused booking writes no cycle row"
    still_draft = api.read_entity(
        "get_production_order", draft_order["id"], ctx["admin_headers"]
    )
    assert still_draft["status"] == "DRAFT", "the unreleased order never moved"
    assert still_draft["version"] == 1, "a refused booking bumps no order version"


def test_terminal_rows_refuse_every_further_trigger(api):
    """An aborted cycle, a cancelled order and a retired tool are all sealed shut.

    PRD.md section 3.5: "`DEMOLDED` and `ABORTED` are both terminal."
    PRD.md section 3.5: "A cycle addressed in the wrong state is refused with
    `ERR_CYCLE_INVALID_STATE` (HTTP 409): `SCHEDULED` is required to start the
    oven, `OVEN_RUNNING` to enter cooling, `COOLING` to demould, and
    `SCHEDULED`, `OVEN_RUNNING` or `COOLING` to abort."
    PRD.md section 3.3: "from `COMPLETE` or `CANCELLED` it is refused with
    `ERR_ORDER_ALREADY_TERMINAL` (HTTP 409)."
    PRD.md section 3.3: "`CANCELLED` is terminal."
    PRD.md section 3.4: "a `DRAFT`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`,
    `COMPLETE` or `CANCELLED` order cannot take a new cycle and is refused with
    `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409)."
    PRD.md section 3.1: "A hold attempted on a tool that is not `AVAILABLE` is
    `ERR_MOLD_NOT_AVAILABLE` (HTTP 409)."
    PRD.md section 3.1: "Completing service requires `status` `MAINTENANCE`"
    PRD.md section 3.1: "Retiring a tool requires a `retire_reason` and
    requires `status` to be `AVAILABLE` or `MAINTENANCE`; `RETIRED` is terminal
    and makes the tool a legal `replaces_mold_id` target."
    PRD.md section 3.5: "every charge of the cycle in `RESERVED` becomes
    `RELEASED` with `released_reason` `CYCLE_ABORTED`, moving `charge_kg` from
    `reserved_kg` back to `available_kg`"

    Design: Corner/state_machines/sm_terminal_lockdown_aborted_cycle_cancelled_order_and_retired_mold_refuse_every_trigger
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    spare_mold = get_success_data(
        api.create_mold(
            mold_payload(
                ctx["product_model_id"], cavity_count=1, nominal_charge_kg=24.0
            ),
            ctx["admin_headers"],
        )
    )
    retired = get_success_data(
        api.retire_mold(
            spare_mold["id"], retire_mold_payload("Superseded"), ctx["admin_headers"]
        )
    )
    assert retired["status"] == "RETIRED", "retiring an idle AVAILABLE tool is accepted"

    lot = create_resin_lot(received_kg=500.0)
    order = create_production_order(ctx, ordered_qty=2)
    cycle = schedule_cycle(ctx, order, oven_start_at="2026-08-01T09:00:00Z")
    charge = reserve_charge(ctx, cycle, lot, charge_kg=24.0)
    aborted = get_success_data(
        api.abort_molding_cycle(
            cycle["id"], abort_payload("OPERATOR_ABORT"), ctx["operator_headers"]
        )
    )
    assert aborted["status"] == "ABORTED", "aborting from SCHEDULED is legal"

    doomed_order = create_production_order(ctx, release=False, ordered_qty=1)
    cancelled = get_success_data(
        api.cancel_production_order(
            doomed_order["id"], cancel_order_payload("first cancel"), ctx["admin_headers"]
        )
    )
    assert cancelled["status"] == "CANCELLED", "cancelling from DRAFT is legal"

    set_clock("2026-08-01T09:00:00Z")
    for response in (
        api.start_oven(
            cycle["id"],
            start_oven_payload("2026-08-01T09:00:00Z"),
            ctx["operator_headers"],
        ),
        api.enter_cooling(
            cycle["id"],
            enter_cooling_payload("2026-08-01T10:00:00Z"),
            ctx["operator_headers"],
        ),
        api.demold(
            cycle["id"],
            demold_payload("2026-08-01T10:35:00Z"),
            ctx["operator_headers"],
        ),
        api.abort_molding_cycle(
            cycle["id"], abort_payload("OPERATOR_ABORT"), ctx["operator_headers"]
        ),
    ):
        validate_error(response, ApiErrorId.CYCLE_INVALID_STATE)

    validate_error(
        api.cancel_production_order(
            doomed_order["id"], cancel_order_payload("second cancel"), ctx["admin_headers"]
        ),
        ApiErrorId.ORDER_ALREADY_TERMINAL,
    )
    validate_error(
        api.create_molding_cycle(
            molding_cycle_payload(
                doomed_order["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(doomed_order["id"]),
                arm_index=2,
                oven_start_at="2026-08-02T09:00:00Z",
            ),
            ctx["operator_headers"],
        ),
        ApiErrorId.ORDER_NOT_SCHEDULABLE,
    )

    for response in (
        api.service_hold_mold(
            spare_mold["id"],
            service_hold_payload("probe on a retired tool"),
            ctx["admin_headers"],
        ),
        api.complete_service_mold(
            spare_mold["id"],
            complete_service_payload("probe on a retired tool"),
            ctx["admin_headers"],
        ),
        api.retire_mold(
            spare_mold["id"], retire_mold_payload("second retire"), ctx["admin_headers"]
        ),
    ):
        validate_error(response, ApiErrorId.MOLD_NOT_AVAILABLE)

    final_cycle = api.read_entity("get_molding_cycle", cycle["id"], ctx["admin_headers"])
    assert final_cycle["status"] == "ABORTED", "four refusals left the cycle ABORTED"
    assert final_cycle["abort_reason"] == "OPERATOR_ABORT", "the abort reason is kept"
    assert final_cycle["version"] == 3, (
        "one bump each for create, the charge roll-up and the abort"
    )

    final_order = api.read_entity(
        "get_production_order", doomed_order["id"], ctx["admin_headers"]
    )
    assert final_order["status"] == "CANCELLED", "the order is still cancelled"
    assert final_order["version"] == 2, "one bump each for create and the cancel"

    final_mold = api.read_entity("get_mold", spare_mold["id"], ctx["admin_headers"])
    assert final_mold["status"] == "RETIRED", "RETIRED is terminal"
    assert final_mold["cycles_since_service"] == 0, "the retired tool never ran"
    assert final_mold["version"] == 2, "one bump each for create and the retire"

    final_lot = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert_decimal_equals(final_lot["available_kg"], "500.000", Q_MASS, "available_kg")
    assert_decimal_equals(final_lot["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(final_lot["consumed_kg"], "0.000", Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(final_lot)

    final_charge = api.read_entity("get_resin_charge", charge["id"], ctx["admin_headers"])
    assert final_charge["status"] == "RELEASED", "the abort released the reservation"
    assert final_charge["released_reason"] == "CYCLE_ABORTED", (
        "the release reason names the abort that caused it"
    )


def test_repeating_a_successful_trigger_is_refused_on_six_machines(api):
    """Replaying a trigger that already fired is refused, and the first effect is not doubled.

    PRD.md section 3.5: "A cycle addressed in the wrong state is refused with
    `ERR_CYCLE_INVALID_STATE` (HTTP 409): `SCHEDULED` is required to start the
    oven, `OVEN_RUNNING` to enter cooling, `COOLING` to demould, and
    `SCHEDULED`, `OVEN_RUNNING` or `COOLING` to abort."
    PRD.md section 3.2: "The charge's `status` must be `RESERVED`, otherwise
    `ERR_CHARGE_NOT_RELEASABLE` (HTTP 409) — a `CONSUMED` charge can never be
    released, because consumption is irreversible."
    PRD.md section 3.2: "The optional `release_reason` supplies
    `released_reason`; when it is omitted, `released_reason` is set to
    `CYCLE_ABORTED`."
    PRD.md section 3.1: "restoring a station that is already up is
    `ERR_OVEN_STATION_ALREADY_OPERATIONAL` (HTTP 409)."
    PRD.md section 3.1: "A bay already down reports `ERR_COOLING_BAY_DOWN`, and
    restoring an operational bay reports
    `ERR_COOLING_BAY_ALREADY_OPERATIONAL`."
    PRD.md section 3.1: "Reinstatement takes no body, requires `status`
    `SUSPENDED`, and otherwise reports `ERR_TECHNICIAN_ALREADY_ACTIVE`
    (HTTP 409)."
    PRD.md section 3.1: "Reinstatement requires `status` `SUSPENDED`, otherwise
    `ERR_CUSTOMER_ALREADY_ACTIVE` (HTTP 409), and it does *not* resurrect a
    voided claim."
    PRD.md section 3.2: "On release `charge_kg` moves from the lot's
    `reserved_kg` back to its `available_kg`"

    Design: Corner/state_machines/sm_idempotency_repeating_a_successful_trigger_is_refused_on_five_machines
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    spare_station = get_success_data(
        api.create_oven_station(oven_station_payload(), ctx["admin_headers"])
    )
    spare_bay = get_success_data(
        api.create_cooling_bay(cooling_bay_payload(), ctx["admin_headers"])
    )
    spare_tech = create_technician("QUALITY_INSPECTOR")
    spare_customer = create_customer()

    lot = create_resin_lot(received_kg=500.0)
    order = create_production_order(ctx, ordered_qty=2)
    cycle_a = schedule_cycle(ctx, order, oven_start_at="2026-08-01T09:00:00Z")
    cycle_b = schedule_cycle(ctx, order, oven_start_at="2026-08-01T11:00:00Z")
    reserve_charge(ctx, cycle_a, lot, charge_kg=24.0)
    charge_b = reserve_charge(ctx, cycle_b, lot, charge_kg=24.0)

    set_clock("2026-08-01T09:00:00Z")
    get_success_data(
        api.start_oven(
            cycle_a["id"],
            start_oven_payload("2026-08-01T09:00:00Z"),
            ctx["operator_headers"],
        )
    )
    get_success_data(
        api.release_resin_charge(
            charge_b["id"], release_charge_payload(), ctx["resin_tech_headers"]
        )
    )
    for entity_id, mark_down, restore in (
        (spare_station["id"], api.mark_down_oven_station, api.restore_oven_station),
        (spare_bay["id"], api.mark_down_cooling_bay, api.restore_cooling_bay),
    ):
        get_success_data(
            mark_down(entity_id, mark_down_payload("Burner service"), ctx["admin_headers"])
        )
        get_success_data(restore(entity_id, ctx["admin_headers"]))
    get_success_data(
        api.suspend_technician(
            spare_tech["technician_id"],
            suspend_payload("Refresher training"),
            ctx["admin_headers"],
        )
    )
    get_success_data(
        api.reinstate_technician(spare_tech["technician_id"], ctx["admin_headers"])
    )
    # PRD.md §4 reserves both customer undo edges to PlantAdmin: "POST
    # `/customers/{customer_id}/suspend` ... PlantAdmin" and "POST
    # `/customers/{customer_id}/reinstate` ... PlantAdmin".
    get_success_data(
        api.suspend_customer(
            spare_customer["customer_id"],
            suspend_payload("Credit hold"),
            ctx["admin_headers"],
        )
    )
    get_success_data(
        api.reinstate_customer(spare_customer["customer_id"], ctx["admin_headers"])
    )

    validate_error(
        api.start_oven(
            cycle_a["id"],
            start_oven_payload("2026-08-01T09:00:00Z"),
            ctx["operator_headers"],
        ),
        ApiErrorId.CYCLE_INVALID_STATE,
    )
    validate_error(
        api.release_resin_charge(
            charge_b["id"], release_charge_payload(), ctx["resin_tech_headers"]
        ),
        ApiErrorId.CHARGE_NOT_RELEASABLE,
    )
    validate_error(
        api.restore_oven_station(spare_station["id"], ctx["admin_headers"]),
        ApiErrorId.OVEN_STATION_ALREADY_OPERATIONAL,
    )
    validate_error(
        api.restore_cooling_bay(spare_bay["id"], ctx["admin_headers"]),
        ApiErrorId.COOLING_BAY_ALREADY_OPERATIONAL,
    )
    validate_error(
        api.reinstate_technician(spare_tech["technician_id"], ctx["admin_headers"]),
        ApiErrorId.TECHNICIAN_ALREADY_ACTIVE,
    )
    validate_error(
        api.reinstate_customer(spare_customer["customer_id"], ctx["admin_headers"]),
        ApiErrorId.CUSTOMER_ALREADY_ACTIVE,
    )

    replayed_cycle = api.read_entity(
        "get_molding_cycle", cycle_a["id"], ctx["admin_headers"]
    )
    assert replayed_cycle["status"] == "OVEN_RUNNING", "the replay did not move the cycle"
    assert_instant_equals(
        replayed_cycle["actual_oven_start_at"],
        "2026-08-01T09:00:00Z",
        "actual_oven_start_at survived the replay",
    )
    assert replayed_cycle["version"] == 3, (
        "one bump each for create, the charge roll-up and start-oven"
    )

    replayed_charge = api.read_entity(
        "get_resin_charge", charge_b["id"], ctx["admin_headers"]
    )
    assert replayed_charge["status"] == "RELEASED", "the charge is still released once"
    assert replayed_charge["released_reason"] == "CYCLE_ABORTED", (
        "an omitted release_reason defaults to CYCLE_ABORTED and the replay did not "
        "rewrite it"
    )
    assert replayed_charge["version"] == 2, "one bump each for reserve and release"

    for label, getter, entity_id, expected_status in (
        ("oven station", "get_oven_station", spare_station["id"], "OPERATIONAL"),
        ("cooling bay", "get_cooling_bay", spare_bay["id"], "OPERATIONAL"),
        ("technician", "get_technician", spare_tech["technician_id"], "ACTIVE"),
        ("customer", "get_customer", spare_customer["customer_id"], "ACTIVE"),
    ):
        row = api.read_entity(getter, entity_id, ctx["admin_headers"])
        assert row["status"] == expected_status, f"{label} is back in {expected_status}"
        assert row["version"] == 3, (
            f"{label}: one bump each for create, the down move and the up move"
        )

    final_lot = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert_decimal_equals(final_lot["available_kg"], "476.000", Q_MASS, "available_kg")
    assert_decimal_equals(final_lot["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(final_lot["consumed_kg"], "24.000", Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(final_lot)


def test_initial_state_of_every_stateful_row_immediately_after_creation(api):
    """Eleven kinds of row land in the initial state the server picks, never the client.

    PRD.md section 2.8: "Derived: `status` (default `DRAFT`, one of `DRAFT`,
    `READY_TO_SCHEDULE`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`, `IN_PRODUCTION`,
    `COMPLETE`, `CANCELLED`); `blocked_reason` (default null, and when set one
    of `NO_QUALIFIED_RESIN_LOT`, `WAREHOUSE_FROZEN`); `completed_qty` and
    `scrapped_qty` (integers, default 0)"
    PRD.md section 2.8: "the actual-time stamps `actual_oven_start_at`,
    `actual_oven_end_at` and `actual_cooling_end_at` (all default null)"
    PRD.md section 2.8: "`status` (default `SCHEDULED`, one of `SCHEDULED`,
    `OVEN_RUNNING`, `COOLING`, `DEMOLDED`, `ABORTED`); and `abort_reason`
    (default null"
    PRD.md section 3.1: "When it is registered, `cycles_since_service` starts at
    0 and `status` at `AVAILABLE`."
    PRD.md section 2.8: "`status` (default `AVAILABLE`, one of `AVAILABLE`,
    `DEPLETED`, `QUARANTINED`, `EXPIRED`)."
    PRD.md section 2.8: "`committed_cube_m3` (four decimals, default 0.0000,
    held equal to the rounded sum of `stored_footprint_cube_m3` over the site's
    units whose `logistics_status` is `STORED` or `LOADED`); `utilization_pct`
    (two decimals, default 0.00); and `posture` (default `NORMAL`, one of
    `NORMAL`, `RESTRICTED`, `FROZEN`)."
    PRD.md section 3.1: "Oven stations and cooling bays each have exactly two
    states, `OPERATIONAL` and `DOWN`, and both begin `OPERATIONAL`."
    PRD.md section 3.1: "A technician is created `ACTIVE` with a `role_code`
    and a `certifications` array; the created identifier is the value that
    person presents as `X-User-ID`."
    PRD.md section 3.1: "starting `ACTIVE` with
    `storage_guidance_acknowledged_at` null."
    PRD.md section 2.8: "`quoted_freight_cents` and `billed_freight_cents`
    (integers, default null); `status` (default `PLANNED`, one of `PLANNED`,
    `LOADING`, `SEALED`, `IN_TRANSIT`, `DELIVERED`, `CANCELLED`); and the stamps
    `sealed_at`, `departed_at` and `delivered_at`, all default null."
    PRD.md section 2.4: "`version` is an integer that starts at 1 when the row
    is created"

    Design: Corner/state_machines/sm_initial_state_of_eleven_machines_immediately_after_creation
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    lot = create_resin_lot(received_kg=500.0)
    customer = create_customer()
    shipment = get_success_data(
        api.create_shipment(shipment_payload(ctx["warehouse_id"]), ctx["planner_headers"])
    )
    draft_order = create_production_order(ctx, release=False, ordered_qty=1)
    live_order = create_production_order(ctx, ordered_qty=1)
    cycle = schedule_cycle(ctx, live_order, oven_start_at="2026-08-01T09:00:00Z")
    charge = reserve_charge(ctx, cycle, lot, charge_kg=24.0)

    order_row = api.read_entity(
        "get_production_order", draft_order["id"], ctx["admin_headers"]
    )
    assert order_row["status"] == "DRAFT", "a new order defaults to DRAFT"
    assert order_row["blocked_reason"] is None, "blocked_reason defaults to null"
    assert order_row["completed_qty"] == 0, "completed_qty defaults to 0"
    assert order_row["scrapped_qty"] == 0, "scrapped_qty defaults to 0"
    assert order_row["version"] == 1, "version starts at 1"

    cycle_row = api.read_entity("get_molding_cycle", cycle["id"], ctx["admin_headers"])
    assert cycle_row["status"] == "SCHEDULED", "a new cycle defaults to SCHEDULED"
    assert cycle_row["abort_reason"] is None, "abort_reason defaults to null"
    for stamp in ("actual_oven_start_at", "actual_oven_end_at", "actual_cooling_end_at"):
        assert cycle_row[stamp] is None, f"{stamp} defaults to null"

    charge_row = api.read_entity("get_resin_charge", charge["id"], ctx["admin_headers"])
    assert charge_row["status"] == "RESERVED", "a new charge is RESERVED"
    assert charge_row["released_reason"] is None, "released_reason defaults to null"
    assert charge_row["version"] == 1, "version starts at 1"

    mold_row = api.read_entity("get_mold", ctx["mold_id"], ctx["admin_headers"])
    assert mold_row["status"] == "AVAILABLE", "a registered tool starts AVAILABLE"
    assert mold_row["cycles_since_service"] == 0, "the service counter starts at 0"
    assert mold_row["replaces_mold_id"] is None, "replaces_mold_id defaults to null"

    lot_row = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert lot_row["status"] == "AVAILABLE", (
        "reserving mass does not change the lot state while available_kg is above 0.000"
    )
    assert_decimal_equals(lot_row["available_kg"], "476.000", Q_MASS, "available_kg")

    site = api.read_entity("get_warehouse", ctx["warehouse_id"], ctx["planner_headers"])
    assert site["posture"] == "NORMAL", "posture defaults to NORMAL"
    assert_decimal_equals(site["committed_cube_m3"], "0.0000", Q_CUBE, "committed_cube_m3")
    assert_decimal_equals(site["utilization_pct"], "0.00", Q_PERCENT, "utilization_pct")
    assert site["version"] == 1, "version starts at 1"

    for label, getter, entity_id in (
        ("oven station", "get_oven_station", ctx["oven_station_id"]),
        ("cooling bay", "get_cooling_bay", ctx["cooling_bay_id"]),
    ):
        row = api.read_entity(getter, entity_id, ctx["admin_headers"])
        assert row["status"] == "OPERATIONAL", f"a new {label} begins OPERATIONAL"
        assert row["version"] == 1, f"{label}: version starts at 1"

    tech_row = api.read_entity(
        "get_technician", ctx["molding_operator_id"], ctx["admin_headers"]
    )
    assert tech_row["status"] == "ACTIVE", "a technician is created ACTIVE"
    assert tech_row["version"] == 1, "version starts at 1"

    customer_row = api.read_entity(
        "get_customer", customer["customer_id"], ctx["planner_headers"]
    )
    assert customer_row["status"] == "ACTIVE", "a customer starts ACTIVE"
    assert customer_row["storage_guidance_acknowledged_at"] is None, (
        "the storage-guidance acknowledgement starts null"
    )
    assert customer_row["version"] == 1, "version starts at 1"

    shipment_row = api.read_entity("get_shipment", shipment["id"], ctx["planner_headers"])
    assert shipment_row["status"] == "PLANNED", "a new trailer defaults to PLANNED"
    assert_decimal_equals(shipment_row["loaded_cube_m3"], "0.0000", Q_CUBE, "loaded_cube")
    assert_decimal_equals(shipment_row["nested_cube_m3"], "0.0000", Q_CUBE, "nested_cube")
    assert_decimal_equals(
        shipment_row["cube_utilization_pct"], "0.00", Q_PERCENT, "cube_utilization_pct"
    )
    for field in (
        "quoted_freight_cents",
        "billed_freight_cents",
        "sealed_at",
        "departed_at",
        "delivered_at",
    ):
        assert shipment_row[field] is None, f"{field} defaults to null"
    assert shipment_row["version"] == 1, "version starts at 1"
