"""Steam curing: the boiler admission test and the two energy accounting variants."""

from test_helpers import (
    ApiErrorId,
    assert_curing_cycle,
    assert_decimal,
    ENERGY_COST_MODELED_CENTS,
    MODELED_THERMS_40BHP,
    TEST_USERS,
    add_bed_and_run,
    cast_run,
    complete_curing_cycle,
    create_curing_cycle,
    create_curing_cycle_payload,
    read_curing_cycle,
    setup_plant,
    setup_production_line,
    validate_error,
    validate_paginated,
    validate_success,
)

SUPERVISOR = TEST_USERS["production_supervisor_headers"]


def test_modeled_therms_is_written_when_the_cycle_is_scheduled(api):
    """PRD §3.4: "At creation the cycle's `modeled_therms` is computed
    immediately from the profile alone and stored."
    PRD §3.4: "Multiplying `steam_demand_bhp` by the
    therm-per-boiler-horsepower-hour factor of 0.335 and then by the weighted
    duration, and rounding half up to two decimal places, gives
    `modeled_therms`."
    PRD §3.4: "The cycle's `bed_run_id` is taken from the run the call is made
    against, and the new cycle begins in `SCHEDULED` with `metered_therms`,
    `energy_therms`, `energy_source`, `energy_variance_pct` and
    `energy_cost_cents` all null and `variance_flagged` false."

    Design: Corner/calculations/curing_modeled_therms_written_at_creation_from_constants
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])

    response = api.create_curing_cycle(
        ctx["run"]["id"], create_curing_cycle_payload(ctx["zone"]["id"]), SUPERVISOR
    )
    cycle = validate_success(response, 201)

    assert_curing_cycle(cycle)
    assert_decimal(cycle["modeled_therms"], MODELED_THERMS_40BHP, 2, "curing_cycle.modeled_therms")
    assert cycle["status"] == "SCHEDULED"
    assert cycle["energy_therms"] is None
    assert cycle["energy_source"] is None
    assert cycle["energy_cost_cents"] is None
    assert cycle["energy_variance_pct"] is None
    assert cycle["variance_flagged"] is False
    assert cycle["bed_run_id"] == ctx["run"]["id"]

    _, meta = validate_paginated(
        api.list_steam_zone_curing_cycles(ctx["zone"]["id"], SUPERVISOR)
    )
    assert meta["total_count"] == 1


def test_metered_reading_bills_the_meter_and_flags_the_variance(api):
    """PRD §3.4: "When `metered_therms` is supplied, the cycle is accounted under
    the `METERED` variant: `energy_source` is set to `METERED`, `energy_therms`
    takes the supplied `metered_therms`, and `energy_variance_pct` is computed
    as the difference between `metered_therms` and `modeled_therms`, divided by
    `modeled_therms`, multiplied by 100 and rounded half up to two decimal
    places."
    PRD §3.4: "In both variants the charge is the same shape: `energy_cost_cents`
    is `energy_therms` multiplied by the supplying zone's
    `therm_rate_cents_per_therm`, rounded half up to a whole number of cents."
    PRD §3.4: "A cycle drawing 40 boiler horsepower, soaking at 150 degrees
    Fahrenheit, ramping at 30 degrees per hour and holding for 8 hours models out
    at 142.38 therms, which at 95 cents per therm bills 13526 cents; if the
    operator instead reports a meter reading of 170.00 therms, the same cycle
    bills 16150 cents and flags a 19.40 percent variance."

    Design: Difficulty/dual_variant_calc/metered_vs_modeled_curing_energy
    """
    ctx = setup_production_line(
        stage="tensioned", with_cylinder_set=False, with_curing_cycle=False
    )
    cycle_a = create_curing_cycle(ctx["run"]["id"], ctx["zone"]["id"])
    cast_run(ctx["run"]["id"])

    completed = validate_success(
        api.complete_curing_cycle(cycle_a["id"], SUPERVISOR, {"metered_therms": 170.00})
    )

    assert_decimal(
        completed["modeled_therms"], MODELED_THERMS_40BHP, 2, "curing_cycle.modeled_therms"
    )
    assert completed["energy_source"] == "METERED"
    assert_decimal(completed["energy_therms"], 170.00, 2, "curing_cycle.energy_therms")
    assert_decimal(
        completed["energy_variance_pct"], 19.40, 2, "curing_cycle.energy_variance_pct"
    )
    assert completed["variance_flagged"] is True
    assert completed["energy_cost_cents"] == 16150, (
        f"170.00 therms at 95 cents bills 16150 cents, got {completed['energy_cost_cents']}"
    )
    assert completed["energy_cost_cents"] != ENERGY_COST_MODELED_CENTS, (
        "the metered charge must differ from the 13526 cents the model would have billed"
    )
    assert completed["status"] == "COMPLETED"


def test_omitting_the_meter_reading_bills_the_model_and_never_flags(api):
    """PRD §3.4: "When `metered_therms` is omitted, the cycle is accounted under
    the `MODELED` variant: `energy_source` is set to `MODELED`, `energy_therms`
    takes the value of `modeled_therms`, and `energy_variance_pct` stays null."
    PRD §3.4: "Under this variant `variance_flagged` stays false no matter how far
    the real boiler drifted, because there is no meter reading to compare
    against."
    PRD §3.4: "In both variants the charge is the same shape: `energy_cost_cents`
    is `energy_therms` multiplied by the supplying zone's
    `therm_rate_cents_per_therm`, rounded half up to a whole number of cents."

    Design: Difficulty/dual_variant_calc/metered_vs_modeled_curing_energy
    """
    ctx = setup_production_line(
        stage="tensioned", with_cylinder_set=False, with_curing_cycle=False
    )
    cycle_a = create_curing_cycle(ctx["run"]["id"], ctx["zone"]["id"])
    cycle_b = create_curing_cycle(
        ctx["run"]["id"],
        ctx["zone"]["id"],
        planned_start="2026-08-04T00:00:00Z",
        planned_end="2026-08-04T06:00:00Z",
        ramp_rate_f_per_hr=40,
        soak_temp_f=140,
        soak_hours=6,
        steam_demand_bhp=30,
    )
    cast_run(ctx["run"]["id"])
    complete_curing_cycle(cycle_a["id"], metered_therms=170.00)

    completed = validate_success(api.complete_curing_cycle(cycle_b["id"], SUPERVISOR, {}))

    assert_decimal(completed["modeled_therms"], 80.40, 2, "curing_cycle.modeled_therms")
    assert completed["energy_source"] == "MODELED"
    assert_decimal(completed["energy_therms"], 80.40, 2, "curing_cycle.energy_therms")
    assert completed["energy_variance_pct"] is None
    assert completed["variance_flagged"] is False
    assert completed["energy_cost_cents"] == 7638, (
        f"80.40 therms at 95 cents bills 7638 cents, got {completed['energy_cost_cents']}"
    )


def test_variance_exactly_at_tolerance_does_not_flag(api):
    """PRD §3.4: "`variance_flagged` is true when `energy_variance_pct` is not
    null and its absolute value is greater than the energy variance tolerance of
    15.0 percent, and false otherwise; a variance of exactly 15.0 percent in
    either direction does not flag."
    PRD §3.4: "The comparison is made against the already-rounded
    `modeled_therms` stored at creation, not against the unrounded product —
    rounding happens before the comparison."

    Design: Corner/calculations/energy_variance_exactly_at_tolerance_is_not_flagged
    """
    ctx = setup_production_line(
        stage="tensioned", with_cylinder_set=False, with_curing_cycle=False
    )
    edge = create_curing_cycle(ctx["run"]["id"], ctx["zone"]["id"])
    over = create_curing_cycle(
        ctx["run"]["id"],
        ctx["zone"]["id"],
        planned_start="2026-08-04T00:00:00Z",
        planned_end="2026-08-04T06:00:00Z",
    )
    cast_run(ctx["run"]["id"])

    at_tolerance = validate_success(
        api.complete_curing_cycle(edge["id"], SUPERVISOR, {"metered_therms": 163.74})
    )
    above_tolerance = validate_success(
        api.complete_curing_cycle(over["id"], SUPERVISOR, {"metered_therms": 163.80})
    )

    assert_decimal(
        at_tolerance["energy_variance_pct"], 15.00, 2, "curing_cycle.energy_variance_pct"
    )
    assert at_tolerance["variance_flagged"] is False, (
        "exactly 15.00 percent is not greater than the 15.0 percent tolerance"
    )
    assert at_tolerance["energy_cost_cents"] == 15555

    assert_decimal(
        above_tolerance["energy_variance_pct"], 15.04, 2, "curing_cycle.energy_variance_pct"
    )
    assert above_tolerance["variance_flagged"] is True
    assert above_tolerance["energy_cost_cents"] == 15561

    for cycle in (at_tolerance, above_tolerance):
        assert cycle["energy_source"] == "METERED"
        assert_decimal(
            cycle["modeled_therms"], MODELED_THERMS_40BHP, 2, "curing_cycle.modeled_therms"
        )


def test_boiler_demand_inside_an_overlap_exceeds_capacity(api):
    """PRD §3.4: "Demand is evaluated at each candidate's `planned_start`: the
    demand at such an instant is the sum of `steam_demand_bhp` over every
    candidate whose `planned_start` is at or before that instant and whose
    `planned_end` is strictly after it."
    PRD §3.4: "If the peak exceeds `boiler_capacity_bhp` the request is rejected
    with `ERR_STEAM_CAPACITY_EXCEEDED`; the comparison is strictly greater, so a
    schedule that exactly saturates the boiler is admitted."

    Design: Difficulty/resource_temporal_overlap/steam_zone_aggregate_boiler_demand_at_half_open_instants
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    _, run_two = add_bed_and_run(ctx, bed_code="B2")
    _, run_three = add_bed_and_run(ctx, bed_code="B3")

    create_curing_cycle(
        ctx["run"]["id"],
        ctx["zone"]["id"],
        planned_start="2026-08-03T12:00:00Z",
        planned_end="2026-08-04T00:00:00Z",
        steam_demand_bhp=40,
    )
    create_curing_cycle(
        run_two["id"],
        ctx["zone"]["id"],
        planned_start="2026-08-03T18:00:00Z",
        planned_end="2026-08-04T06:00:00Z",
        steam_demand_bhp=40,
    )

    # 40 + 40 + 30 = 110 bhp at 20:00 on 2026-08-03, above the 100 bhp boiler.
    response = api.create_curing_cycle(
        run_three["id"],
        create_curing_cycle_payload(
            ctx["zone"]["id"],
            planned_start="2026-08-03T20:00:00Z",
            planned_end="2026-08-03T22:00:00Z",
            soak_hours=1,
            steam_demand_bhp=30,
        ),
        SUPERVISOR,
    )
    validate_error(response, ApiErrorId.ERR_STEAM_CAPACITY_EXCEEDED.value, 409)

    _, meta = validate_paginated(
        api.list_steam_zone_curing_cycles(ctx["zone"]["id"], SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 2, "the rejected cycle must not persist"


def test_cycle_starting_when_another_ends_saturates_the_boiler_exactly(api):
    """PRD §3.4: "Each candidate occupies the half-open interval from its
    `planned_start` up to but not including its `planned_end`, so a cycle that
    ends at a given instant and one that starts at that same instant never
    overlap."
    PRD §3.4: "If the peak exceeds `boiler_capacity_bhp` the request is rejected
    with `ERR_STEAM_CAPACITY_EXCEEDED`; the comparison is strictly greater, so a
    schedule that exactly saturates the boiler is admitted."

    Design: Difficulty/resource_temporal_overlap/steam_zone_aggregate_boiler_demand_at_half_open_instants
    """
    ctx = setup_production_line(stage="scheduled", piece_specs=[])
    _, run_two = add_bed_and_run(ctx, bed_code="B2")
    _, run_three = add_bed_and_run(ctx, bed_code="B3")

    cycle_a = create_curing_cycle(
        ctx["run"]["id"],
        ctx["zone"]["id"],
        planned_start="2026-08-03T12:00:00Z",
        planned_end="2026-08-04T00:00:00Z",
        steam_demand_bhp=40,
    )
    cycle_b = create_curing_cycle(
        run_two["id"],
        ctx["zone"]["id"],
        planned_start="2026-08-03T18:00:00Z",
        planned_end="2026-08-04T06:00:00Z",
        steam_demand_bhp=40,
    )

    # At 00:00 on 2026-08-04 cycle A has already ended, so the peak is 40 + 60.
    response = api.create_curing_cycle(
        run_three["id"],
        create_curing_cycle_payload(
            ctx["zone"]["id"],
            planned_start="2026-08-04T00:00:00Z",
            planned_end="2026-08-04T04:00:00Z",
            soak_hours=2,
            steam_demand_bhp=60,
        ),
        SUPERVISOR,
    )
    admitted = validate_success(response, 201)

    assert admitted["status"] == "SCHEDULED"
    assert admitted["steam_demand_bhp"] == 60
    rows, meta = validate_paginated(
        api.list_steam_zone_curing_cycles(ctx["zone"]["id"], SUPERVISOR, {"limit": 100})
    )
    assert meta["total_count"] == 3
    assert {c["id"] for c in rows} == {cycle_a["id"], cycle_b["id"], admitted["id"]}
    assert cycle_a["steam_demand_bhp"] == 40 and cycle_b["steam_demand_bhp"] == 40


def test_completing_a_completed_cycle_is_refused(api):
    """PRD §3.4: "**Completing** a curing cycle moves it `RUNNING → COMPLETED`
    and is refused with `ERR_CURING_CYCLE_INVALID_STATE` from any other status."
    PRD §3.4: "When `metered_therms` is omitted, the cycle is accounted under the
    `MODELED` variant: `energy_source` is set to `MODELED`, `energy_therms`
    takes the value of `modeled_therms`, and `energy_variance_pct` stays null."

    Design: Corner/state_machines/curing_cycle_complete_twice_returns_invalid_state
    """
    ctx = setup_production_line(stage="curing", with_cylinder_set=False)
    complete_curing_cycle(ctx["curing_cycle"]["id"])

    response = api.complete_curing_cycle(
        ctx["curing_cycle"]["id"], SUPERVISOR, {"metered_therms": 500.00}
    )
    validate_error(response, ApiErrorId.ERR_CURING_CYCLE_INVALID_STATE.value, 409)

    cycle = read_curing_cycle(ctx["run"]["id"], ctx["curing_cycle"]["id"])
    assert cycle["energy_source"] == "MODELED", "the rejected call must not re-account the cycle"
    assert_decimal(cycle["energy_therms"], MODELED_THERMS_40BHP, 2, "curing_cycle.energy_therms")
    assert cycle["energy_cost_cents"] == ENERGY_COST_MODELED_CENTS
    assert cycle["metered_therms"] is None
