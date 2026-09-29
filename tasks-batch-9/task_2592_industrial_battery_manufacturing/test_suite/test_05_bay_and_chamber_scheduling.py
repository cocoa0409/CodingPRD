"""Bay window reservation, chamber power allocation and refusal precedence."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import assert_close
from test_helpers.factories import (
    capacity_test_payload,
    env_hold_payload,
    formation_run_payload,
)
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def test_bay_cooldown_buffer_bites_on_the_right_edge_but_not_at_the_boundary_minute(
    world: World,
):
    """A run ending at 12:00 blocks a 12:30 start and admits a 12:45 start.

    "A requested window collides with an existing run on the same bay whose `run_state` is
    `SCHEDULED` or `CHARGING` when both of these hold at once: the requested start is strictly
    earlier than that existing run's end advanced by the bay's `cooldown_minutes`, and the
    requested end advanced by the same `cooldown_minutes` is strictly later than that existing
    run's start." With a 45-minute cooldown the buffered end is 12:45, so 12:30 collides and
    12:45 does not.

    Design: Difficulty/resource_temporal_overlap/formation_bay_single_occupancy_with_two_sided_cooldown_buffer
    """
    bay_id = world.add_bay("BAY-1", cooldown_minutes=45)
    lot1 = world.lot_in_state(C.LOT_FORMATION, "LOT-I1", 9)
    lot2 = world.lot_in_state(C.LOT_FORMATION, "LOT-I2", 9)
    world.schedule_run(lot1["id"], bay_id, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z")

    validate_error(
        world.api.create_formation_run(
            formation_run_payload(
                lot2["id"], bay_id, "2026-09-02T12:30:00Z", "2026-09-02T14:00:00Z"
            ),
            world.sup_a,
        ),
        E.ERR_BAY_WINDOW_CONFLICT,
    )

    accepted = validate_success(
        world.api.create_formation_run(
            formation_run_payload(
                lot2["id"], bay_id, "2026-09-02T12:45:00Z", "2026-09-02T14:00:00Z"
            ),
            world.sup_a,
        ),
        201,
    )
    assert accepted["run_state"] == C.RUN_STATE_SCHEDULED

    rows, _ = validate_paginated(
        world.api.list_formation_runs(world.admin, {"bay_id": bay_id})
    )
    assert len(rows) == 2, rows


def test_bay_cooldown_buffer_bites_on_the_left_edge_too(world: World):
    """A window ending at 05:20 collides with a run starting at 06:00, one ending at 05:00 does not.

    "the requested end advanced by the same `cooldown_minutes` is strictly later than that
    existing run's start." 05:20 advanced by 45 minutes is 06:05, which is strictly later than
    06:00, while 05:00 advanced by 45 minutes is 05:45 and is not.

    Design: Difficulty/resource_temporal_overlap/formation_bay_single_occupancy_with_two_sided_cooldown_buffer
    """
    bay_id = world.add_bay("BAY-1", cooldown_minutes=45)
    lot1 = world.lot_in_state(C.LOT_FORMATION, "LOT-I1", 9)
    lot3 = world.lot_in_state(C.LOT_FORMATION, "LOT-I3", 9)
    world.schedule_run(lot1["id"], bay_id, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z")

    validate_error(
        world.api.create_formation_run(
            formation_run_payload(
                lot3["id"], bay_id, "2026-09-02T04:00:00Z", "2026-09-02T05:20:00Z"
            ),
            world.sup_a,
        ),
        E.ERR_BAY_WINDOW_CONFLICT,
    )
    reserved_after_refusal = world.read_plant()["emission_reserved_g"]
    assert_close(reserved_after_refusal, 255.00, "emission_reserved_g", 2)

    accepted = validate_success(
        world.api.create_formation_run(
            formation_run_payload(
                lot3["id"], bay_id, "2026-09-02T04:00:00Z", "2026-09-02T05:00:00Z"
            ),
            world.sup_a,
        ),
        201,
    )
    assert accepted["run_state"] == C.RUN_STATE_SCHEDULED
    assert world.read_plant()["formation_energy_charge_cents"] == 0


def test_chamber_admits_concurrent_tests_up_to_the_cap_and_refuses_the_instant_above_it(
    testing_world: World,
):
    """Two overlapping tests may sum exactly to the cap; a third kilowatt is refused.

    "over every instant covered by the requested window -- treated as half-open, including the
    start instant and excluding the end instant -- the sum of `draw_kw` across the `SCHEDULED`
    tests on that same chamber whose windows overlap that instant, plus the requested `draw_kw`,
    must be at most the chamber's `power_cap_kw`. A total landing exactly on the cap is
    **accepted**; only a total strictly above it is refused, with
    `ERR_CHAMBER_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/test_chamber_aggregate_draw_over_half_open_windows
    """
    world = testing_world
    world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T08:00:00Z",
        "2026-09-03T10:00:00Z",
        draw_kw=6.00,
    )
    at_the_cap = world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T09:00:00Z",
        "2026-09-03T11:00:00Z",
        draw_kw=4.00,
    )
    assert at_the_cap["test_state"] == C.TEST_STATE_SCHEDULED

    validate_error(
        world.api.create_capacity_test(
            capacity_test_payload(
                world.assembly_id,
                world.chamber_id,
                "2026-09-03T09:30:00Z",
                "2026-09-03T09:45:00Z",
                draw_kw=1.00,
            ),
            world.qa_a,
        ),
        E.ERR_CHAMBER_CAPACITY_EXCEEDED,
    )

    rows, _ = validate_paginated(
        world.api.list_capacity_tests(world.qa_a, {"chamber_id": world.chamber_id})
    )
    assert len(rows) == 2, rows


def test_adjacent_chamber_windows_never_contend_but_overlapping_ones_do(
    testing_world: World,
):
    """A test starting the instant another ends contends with nothing.

    "Because the intervals are half-open, adjacent windows never overlap: a test starting at the
    precise instant another ends contends with nothing." The 10:00 start therefore sees only its
    own draw, while a later window overlapping it pushes the total to 11.00 kW against a 10.00 kW
    cap and is refused. The chamber's own status is untouched throughout.

    Design: Difficulty/resource_temporal_overlap/test_chamber_aggregate_draw_over_half_open_windows
    """
    world = testing_world
    world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T08:00:00Z",
        "2026-09-03T10:00:00Z",
        draw_kw=6.00,
    )
    adjacent = world.schedule_test(
        world.assembly_id,
        world.chamber_id,
        "2026-09-03T10:00:00Z",
        "2026-09-03T12:00:00Z",
        draw_kw=5.00,
    )
    assert adjacent["test_state"] == C.TEST_STATE_SCHEDULED

    validate_error(
        world.api.create_capacity_test(
            capacity_test_payload(
                world.assembly_id,
                world.chamber_id,
                "2026-09-03T11:00:00Z",
                "2026-09-03T12:00:00Z",
                draw_kw=6.00,
            ),
            world.qa_a,
        ),
        E.ERR_CHAMBER_CAPACITY_EXCEEDED,
    )

    chamber = validate_success(
        world.api.get_test_chamber(world.chamber_id, world.admin), 200
    )
    assert chamber["chamber_status"] == C.CHAMBER_AVAILABLE


def test_lot_state_is_reported_ahead_of_the_emission_budget_breach(make_world):
    """A lot outside FORMATION on an over-budget plant returns the state error.

    "When several checks would fail on the same request, exactly one error is returned: the one
    belonging to the **lowest-numbered tier** below that fails." State legality is tier 11 and
    the emission quota is a later tier, so a lot still in `PLATE_PRODUCTION` is refused for its
    state even though the reservation of 255.00 g would also blow a 100.00 g permit.

    Design: Difficulty/priority_pair_validation_conflict/lot_state_beats_emission_budget_on_run_scheduling
    """
    world = make_world(plant_overrides={"monthly_lead_emission_permit_g": 100.00})
    bay1 = world.add_bay("BAY-1")
    bay2 = world.add_bay("BAY-2")
    lot_a = world.lot_in_state(C.LOT_PLATE_PRODUCTION, "LOT-A", 9)
    lot_b = world.lot_in_state(C.LOT_FORMATION, "LOT-B", 9)

    validate_error(
        world.api.create_formation_run(
            formation_run_payload(
                lot_a["id"], bay1, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"
            ),
            world.sup_a,
        ),
        E.ERR_LOT_STATE_INVALID,
    )

    validate_error(
        world.api.create_formation_run(
            formation_run_payload(
                lot_b["id"], bay2, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"
            ),
            world.sup_a,
        ),
        E.ERR_EMISSION_BUDGET_EXCEEDED,
    )

    assert_close(world.read_plant()["emission_reserved_g"], 0.00, "emission_reserved_g", 2)
    rows, _ = validate_paginated(world.api.list_formation_runs(world.admin))
    assert rows == [], rows


def test_environmental_hold_is_reported_ahead_of_the_bay_window_conflict(world: World):
    """A held lot is refused for the hold, and only after release does the bay conflict surface.

    "`ERR_LOT_ENV_HELD` guards ten operations: `POST /production-lots/{id}/advance`, `POST
    /production-lots/{id}/sampling-plans`" and among them `POST /formation-runs`, and that safety
    tier precedes the window tier. Once the hold is lifted the identical request is refused
    instead by the cooldown buffer, because 12:30 is still inside 12:00 advanced by 45 minutes.

    Design: Difficulty/priority_pair_validation_conflict/env_hold_beats_bay_window_conflict_on_run_scheduling
    """
    bay_id = world.add_bay("BAY-1", cooldown_minutes=45)
    lot_c = world.lot_in_state(C.LOT_FORMATION, "LOT-C", 9)
    lot_d = world.lot_in_state(C.LOT_FORMATION, "LOT-D", 9)
    world.schedule_run(lot_c["id"], bay_id, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z")

    held = validate_success(
        world.api.env_hold_lot(
            lot_d["id"],
            env_hold_payload("HOLD", C.HOLD_REASON_OPERATOR),
            world.saf_a,
        ),
        200,
    )
    assert held["env_hold_status"] == C.ENV_HOLD_HELD

    conflicting = formation_run_payload(
        lot_d["id"], bay_id, "2026-09-02T12:30:00Z", "2026-09-02T14:00:00Z"
    )
    validate_error(
        world.api.create_formation_run(conflicting, world.sup_a), E.ERR_LOT_ENV_HELD
    )

    released = world.release_hold(lot_d["id"])
    assert released["env_hold_status"] == C.ENV_HOLD_CLEAR

    validate_error(
        world.api.create_formation_run(conflicting, world.sup_a), E.ERR_BAY_WINDOW_CONFLICT
    )

    lot_after = world.read_lot(lot_d["id"])
    assert lot_after["process_state"] == C.LOT_FORMATION
    assert lot_after["env_hold_status"] == C.ENV_HOLD_CLEAR
    rows, _ = validate_paginated(
        world.api.list_formation_runs(world.admin, {"bay_id": bay_id})
    )
    assert len(rows) == 1, rows


def test_the_state_refusal_survives_the_removal_of_the_emission_breach(make_world):
    """Raising the permit does not turn the state refusal into an acceptance.

    State legality is "**Tier 11 -- state legality.** All HTTP 409 ... `ERR_LOT_STATE_INVALID`
    guards `POST /production-lots/{id}/advance`" and, among the endpoints listed there, `POST
    /formation-runs`; the quota lives two tiers later, at "**Tier 16 -- fiscal and quota.**
    `ERR_EMISSION_BUDGET_EXCEEDED` (409) guards `POST /formation-runs`." Amending the allowance is a
    plain plant edit, because "the utilization ratio is recomputed against the new allowance and the
    posture is re-derived in the same request", so the only difference between the refused call and
    the accepted one is which lot is named.

    Design: Difficulty/priority_pair_validation_conflict/lot_state_beats_emission_budget_on_run_scheduling
    """
    world = make_world(plant_overrides={"monthly_lead_emission_permit_g": 100.00})
    bay1 = world.add_bay("BAY-1")
    bay2 = world.add_bay("BAY-2")
    lot_a = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-A", 9)
    lot_b = world.lot_in_state(C.LOT_FORMATION, "LOT-B", 9)
    blocked = formation_run_payload(
        lot_a["id"], bay1, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"
    )

    validate_error(
        world.api.create_formation_run(blocked, world.sup_a), E.ERR_LOT_STATE_INVALID
    )

    amended = validate_success(
        world.api.update_plant(
            world.plant_id, {"monthly_lead_emission_permit_g": 100000.00}, world.admin
        ),
        200,
    )
    assert_close(
        amended["monthly_lead_emission_permit_g"],
        100000.00,
        "monthly_lead_emission_permit_g",
        2,
    )
    assert_close(
        amended["emission_utilization_ratio"], 0.0000, "emission_utilization_ratio", 4
    )
    assert amended["compliance_posture"] == C.POSTURE_OPEN

    validate_error(
        world.api.create_formation_run(blocked, world.sup_a), E.ERR_LOT_STATE_INVALID
    )

    accepted = validate_success(
        world.api.create_formation_run(
            formation_run_payload(
                lot_b["id"], bay2, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"
            ),
            world.sup_a,
        ),
        201,
    )
    assert_close(accepted["reserved_emission_g"], 255.00, "reserved_emission_g", 2)

    rows, meta = validate_paginated(
        world.api.list_formation_runs(world.admin, {"bay_id": bay2})
    )
    assert meta["total_count"] == 1, rows
    assert rows[0]["lot_id"] == lot_b["id"]
    refused_rows, refused_meta = validate_paginated(
        world.api.list_formation_runs(world.admin, {"bay_id": bay1})
    )
    assert refused_meta["total_count"] == 0, refused_rows
    assert_close(
        world.read_plant()["emission_utilization_ratio"],
        0.0026,
        "emission_utilization_ratio",
        4,
    )


def test_the_hold_is_reported_ahead_of_an_impossible_window_too(world: World):
    """The same held lot masks the window check, which surfaces only once the hold is lifted.

    "`ERR_LOT_ENV_HELD` guards ten operations" including `POST /formation-runs`, and it is a tier-12
    refusal, while "`ERR_WINDOW_INVALID` (422) guards `POST /formation-runs` and `POST
    /capacity-tests`" one tier group later at tier 15. The window rule itself is strict: "The planned
    end must be strictly after the planned start, otherwise `ERR_WINDOW_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/env_hold_beats_bay_window_conflict_on_run_scheduling
    """
    bay_id = world.add_bay("BAY-1", cooldown_minutes=45)
    lot = world.lot_in_state(C.LOT_FORMATION, "LOT-D", 9)
    world.hold_lot(lot["id"])

    empty_window = formation_run_payload(
        lot["id"], bay_id, "2026-09-02T06:00:00Z", "2026-09-02T06:00:00Z"
    )
    validate_error(
        world.api.create_formation_run(empty_window, world.sup_a), E.ERR_LOT_ENV_HELD
    )

    world.release_hold(lot["id"])
    validate_error(
        world.api.create_formation_run(empty_window, world.sup_a), E.ERR_WINDOW_INVALID
    )

    rows, meta = validate_paginated(world.api.list_formation_runs(world.admin))
    assert rows == [], rows
    assert meta["total_count"] == 0

    scheduled = world.schedule_run(
        lot["id"], bay_id, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"
    )
    assert scheduled["run_state"] == C.RUN_STATE_SCHEDULED
    rows_after, meta_after = validate_paginated(
        world.api.list_formation_runs(world.admin, {"bay_id": bay_id})
    )
    assert meta_after["total_count"] == 1, rows_after
    assert rows_after[0]["id"] == scheduled["id"]
