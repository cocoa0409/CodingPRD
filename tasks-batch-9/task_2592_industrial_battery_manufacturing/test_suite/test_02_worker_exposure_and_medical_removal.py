"""Industrial-hygiene exposure indices, medical removal and the plant posture."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import assert_close, assert_posture, assert_same_instant
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def test_air_variant_is_a_duration_weighted_mean_over_the_ninety_day_window(world: World):
    """Two air samples of equal duration average to their arithmetic mean concentration.

    "Within that window the time-weighted average is the sum, over samples, of the airborne
    concentration multiplied by that sample's duration in minutes, divided by the sum of those
    durations, rounded half up to three decimal places." A single 60.00 ug/m3 sample scores
    120.00 against the 50 ug/m3 limit, and a second 20.00 ug/m3 sample of the same 480-minute
    duration pulls the weighted mean to 40.000 for an index of 80.00 under the same variant.

    Design: Difficulty/dual_variant_calc/worker_exposure_air_twa_90d_vs_blood_peak_180d
    """
    worker_id = world.add_worker("Pat Paster", "PRODUCTION")

    first = world.record_air(worker_id, "2026-08-15T14:00:00Z", 60.00, 480)
    assert_close(first["resulting_worker_index"], 120.00, "resulting_worker_index", 2)
    assert first["resulting_variant"] == "AIR_TWA_90D"

    second = world.record_air(worker_id, "2026-08-20T14:00:00Z", 20.00, 480)
    assert_close(second["resulting_worker_index"], 80.00, "resulting_worker_index", 2)
    assert second["resulting_variant"] == "AIR_TWA_90D"
    assert second["triggered_removal"] is False

    worker = world.read_worker(worker_id)
    assert_close(worker["exposure_index"], 80.00, "exposure_index", 2)
    assert worker["exposure_index_variant"] == "AIR_TWA_90D"
    assert_same_instant(worker["last_sample_at"], "2026-08-20T14:00:00Z", "last_sample_at")


def test_blood_variant_is_an_unweighted_peak_and_disagrees_with_the_air_variant(
    world: World,
):
    """Air and blood readings on the same worker on the same day produce different indices.

    "Air samples never enter the blood variant and blood samples never enter the air variant,
    so the two variants read disjoint slices of the same append-only log and will generally
    disagree for the same worker on the same day". A 40.00 ug/m3 air sample yields 80.00 and
    leaves the worker on the floor, while a 33.0 ug/dL blood reading yields 110.00 against the
    30 ug/dL limit and removes them.

    Design: Difficulty/dual_variant_calc/worker_exposure_air_twa_90d_vs_blood_peak_180d
    """
    worker_id = world.add_worker("Pat Paster", "PRODUCTION")

    air = world.record_air(worker_id, "2026-08-15T14:00:00Z", 40.00, 480)
    assert_close(air["resulting_worker_index"], 80.00, "resulting_worker_index", 2)
    assert air["triggered_removal"] is False
    assert world.read_worker(worker_id)["removal_status"] == C.REMOVAL_ACTIVE

    blood = world.record_blood(worker_id, "2026-08-25T09:00:00Z", 33.0)
    assert_close(blood["resulting_worker_index"], 110.00, "resulting_worker_index", 2)
    assert blood["resulting_variant"] == "BLOOD_PEAK_180D"
    assert blood["triggered_removal"] is True

    worker = world.read_worker(worker_id)
    assert_close(worker["exposure_index"], 110.00, "exposure_index", 2)
    assert worker["exposure_index_variant"] == "BLOOD_PEAK_180D"
    assert worker["removal_status"] == C.REMOVAL_MEDICAL
    assert worker["removal_count"] == 1

    view = validate_success(world.api.get_exposure_index(worker_id, world.saf_a), 200)
    assert_close(view["air_twa_90d_index"], 80.00, "air_twa_90d_index", 2)
    assert_close(view["blood_peak_180d_index"], 110.00, "blood_peak_180d_index", 2)
    assert_close(view["governing_index"], 110.00, "governing_index", 2)
    assert view["governing_variant"] == "BLOOD_PEAK_180D"
    assert view["removal_eligible"] is True

    plant = world.read_plant()
    assert plant["open_medical_removal_count"] == 1
    assert_posture(plant, C.POSTURE_RESTRICTED)


def test_blood_index_of_exactly_one_hundred_removes_the_worker(world: World):
    """A reading exactly on the 30 ug/dL limit scores 100.00 and takes the worker off duty.

    "When the resulting index reaches 100.00 or more, the worker moves `ACTIVE ->
    MEDICAL_REMOVAL`, `removal_count` is incremented by 1, `triggered_removal` is recorded as
    true on the sample, and the environmental cascade of §2.8 runs through the plant's removal
    count and posture." One open removal is exactly one, so the plant restricts rather than
    freezes.

    Design: Difficulty/boundary_precision_check/blood_lead_index_exactly_100_removes_but_99_67_does_not
    """
    worker_id = world.add_worker("Pat Paster", "PRODUCTION")

    sample = world.record_blood(worker_id, "2026-08-31T09:00:00Z", 30.0)
    assert_close(sample["resulting_worker_index"], 100.00, "resulting_worker_index", 2)
    assert sample["resulting_variant"] == "BLOOD_PEAK_180D"
    assert sample["triggered_removal"] is True

    worker = world.read_worker(worker_id)
    assert worker["removal_status"] == C.REMOVAL_MEDICAL
    assert worker["removal_count"] == 1

    plant = world.read_plant()
    assert plant["open_medical_removal_count"] == 1
    assert_posture(plant, C.POSTURE_RESTRICTED)


def test_blood_index_of_ninety_nine_point_six_seven_keeps_the_worker_on_duty(world: World):
    """29.9 ug/dL rounds half up to 99.67 and stays below the removal threshold.

    "The index is the single highest blood-lead reading in that window divided by the
    blood-lead limit of 30 micrograms per decilitre, multiplied by 100, rounded half up to two
    decimal places." 29.9 / 30 * 100 is 99.6666..., which rounds to 99.67 rather than
    truncating to 99.66, and "an index of exactly 100.00 removes the worker and an index of
    99.99 does not", so this worker keeps working and the sub-threshold sample is still
    retained by the append-only log.

    Design: Difficulty/boundary_precision_check/blood_lead_index_exactly_100_removes_but_99_67_does_not
    """
    worker_id = world.add_worker("Quinn Caster", "PRODUCTION")

    sample = world.record_blood(worker_id, "2026-08-31T09:00:00Z", 29.9)
    assert_close(sample["resulting_worker_index"], 99.67, "resulting_worker_index", 2)
    assert sample["triggered_removal"] is False

    worker = world.read_worker(worker_id)
    assert_close(worker["exposure_index"], 99.67, "exposure_index", 2)
    assert worker["removal_status"] == C.REMOVAL_ACTIVE
    assert worker["removal_count"] == 0

    plant = world.read_plant()
    assert plant["open_medical_removal_count"] == 0
    assert_posture(plant, C.POSTURE_OPEN)

    rows, _ = validate_paginated(world.api.list_exposure_samples(worker_id, world.saf_a))
    assert len(rows) == 1, rows
    assert_close(rows[0]["blood_lead_ug_per_dl"], 29.9, "blood_lead_ug_per_dl", 1)


def test_second_removal_freezes_the_plant_holds_the_lot_and_aborts_the_charging_run(
    formation_world: World,
):
    """One hygiene sample propagates through worker, plant, lot, run and emission ledger.

    "Hop four fires only when the posture became `FROZEN`: every `ProductionLot` of that plant
    whose `process_state` is one of `PLANNED`, `PLATE_PRODUCTION`, `FORMATION`, `ASSEMBLY`,
    `LOT_TESTING` or `QUARANTINED` moves its `env_hold_status` from `CLEAR` to `HELD` with
    `hold_reason` set to `PLANT_FROZEN`." Hop five then aborts the charging run with
    `ENV_HOLD_CASCADE` and hands its reserved grams back, while the freeze driven by two open
    removals survives the released ratio.

    Design: Difficulty/transitive_cascade/cascade_a_exposure_removal_freezes_plant_holds_lots_aborts_runs
    """
    world = formation_world
    wx_id = world.add_worker("Pat Paster", "PRODUCTION")
    wy_id = world.add_worker("Quinn Caster", "PRODUCTION")

    run = world.schedule_run(world.lot_id, world.bay_id)
    assert_close(run["reserved_emission_g"], 255.00, "reserved_emission_g", 2)
    world.set_clock("2026-09-02T06:00:00Z")
    charging = world.start_run(run["id"])
    assert charging["run_state"] == C.RUN_STATE_CHARGING

    first = world.record_blood(wx_id, "2026-09-02T05:00:00Z", 35.0)
    assert_close(first["resulting_worker_index"], 116.67, "resulting_worker_index", 2)
    assert_posture(world.read_plant(), C.POSTURE_RESTRICTED)
    assert world.read_run(run["id"])["run_state"] == C.RUN_STATE_CHARGING

    second = world.record_blood(wy_id, "2026-09-02T05:30:00Z", 30.0)
    assert_close(second["resulting_worker_index"], 100.00, "resulting_worker_index", 2)
    assert second["triggered_removal"] is True
    assert world.read_worker(wy_id)["removal_status"] == C.REMOVAL_MEDICAL
    assert world.read_worker(wy_id)["removal_count"] == 1

    plant = world.read_plant()
    assert plant["open_medical_removal_count"] == 2
    assert_posture(plant, C.POSTURE_FROZEN)

    lot = world.read_lot(world.lot_id)
    assert lot["env_hold_status"] == C.ENV_HOLD_HELD
    assert lot["hold_reason"] == C.HOLD_REASON_PLANT_FROZEN
    assert lot["process_state"] == C.LOT_FORMATION

    aborted = world.read_run(run["id"])
    assert aborted["run_state"] == C.RUN_STATE_ABORTED
    assert aborted["abort_reason"] == C.ABORT_ENV_HOLD_CASCADE
    assert aborted["provisional_charge_cents"] == 2210

    plant = world.read_plant()
    assert_close(plant["emission_reserved_g"], 0.00, "emission_reserved_g", 2)
    assert_close(plant["emission_consumed_g"], 0.00, "emission_consumed_g", 2)
    assert plant["formation_energy_charge_cents"] == 0
    assert_posture(plant, C.POSTURE_FROZEN)


def test_a_single_removal_restricts_without_holding_lots_or_aborting_runs(
    formation_world: World,
):
    """The hold-and-abort hops are reserved for the freeze, not for a restriction.

    "Hop three, because that count changed, recomputes the plant's `compliance_posture` -- one
    open removal yields `RESTRICTED`, two or more yield `FROZEN`." With exactly one removal the
    lot keeps a `CLEAR` hold and the charging run keeps both its state and its reservation.

    Design: Difficulty/transitive_cascade/cascade_a_exposure_removal_freezes_plant_holds_lots_aborts_runs
    """
    world = formation_world
    worker_id = world.add_worker("Pat Paster", "PRODUCTION")

    run = world.schedule_run(world.lot_id, world.bay_id)
    world.set_clock("2026-09-02T06:00:00Z")
    world.start_run(run["id"])

    world.record_blood(worker_id, "2026-09-02T05:00:00Z", 35.0)

    plant = world.read_plant()
    assert plant["open_medical_removal_count"] == 1
    assert_posture(plant, C.POSTURE_RESTRICTED)
    assert_close(plant["emission_reserved_g"], 255.00, "emission_reserved_g", 2)

    lot = world.read_lot(world.lot_id)
    assert lot["env_hold_status"] == C.ENV_HOLD_CLEAR
    assert lot["hold_reason"] is None

    still_charging = world.read_run(run["id"])
    assert still_charging["run_state"] == C.RUN_STATE_CHARGING
    assert still_charging["abort_reason"] is None


def test_medical_clearance_on_another_aggregate_unblocks_an_unchanged_run_start(
    formation_world: World,
):
    """The same start request is refused while the plant is RESTRICTED and accepted once it is OPEN.

    "A start requires the run to be `SCHEDULED`, the lot to be in `FORMATION` with a `CLEAR`
    hold, the bay to be `AVAILABLE`, and -- the strictest cross-entity gate in the system -- the
    plant's posture to be `OPEN`." Nothing about the run changes between the two attempts: only
    a worker's return to duty moves the plant's removal count back to zero.

    Design: Difficulty/cross_entity_state_dependency/formation_run_start_requires_open_plant_posture
    """
    world = formation_world
    worker_id = world.add_worker("Pat Paster", "PRODUCTION")
    run = world.schedule_run(world.lot_id, world.bay_id)

    removed = world.record_blood(worker_id, "2026-08-31T09:00:00Z", 45.0)
    assert_close(removed["resulting_worker_index"], 150.00, "resulting_worker_index", 2)
    assert_posture(world.read_plant(), C.POSTURE_RESTRICTED)

    world.set_clock("2026-09-02T06:00:00Z")
    refused = world.api.start_formation_run(run["id"], world.sup_a)
    validate_error(refused, E.ERR_PLANT_RESTRICTED)
    assert world.read_run(run["id"])["run_state"] == C.RUN_STATE_SCHEDULED
    assert world.read_lot(world.lot_id)["process_state"] == C.LOT_FORMATION

    world.record_blood(worker_id, "2026-09-02T05:00:00Z", 15.0)
    cleared = world.clear_worker(worker_id, "BLL 15.0 on 2026-09-02, fit for duty")
    assert cleared["removal_status"] == C.REMOVAL_ACTIVE
    assert cleared["removal_count"] == 1

    plant = world.read_plant()
    assert plant["open_medical_removal_count"] == 0
    assert_posture(plant, C.POSTURE_OPEN)

    started = validate_success(world.api.start_formation_run(run["id"], world.sup_a), 200)
    assert started["run_state"] == C.RUN_STATE_CHARGING
    assert_same_instant(started["actual_start_at"], "2026-09-02T06:00:00Z", "actual_start_at")


def test_a_restricted_plant_still_accepts_scheduling_but_never_a_start(
    formation_world: World,
):
    """The restriction gate is attached to the start surface, not to the scheduling surface.

    "`ERR_PLANT_RESTRICTED` guards exactly two operations: `POST /production-lots/{id}/advance`
    when `to_state` is `FORMATION`, and `POST /formation-runs/{id}/start`." A restricted plant
    may therefore keep booking bay windows and reserving grams while every attempt to energise a
    bay is refused.

    Design: Difficulty/cross_entity_state_dependency/formation_run_start_requires_open_plant_posture
    """
    world = formation_world
    worker_id = world.add_worker("Pat Paster", "PRODUCTION")
    world.record_blood(worker_id, "2026-08-31T09:00:00Z", 45.0)
    assert_posture(world.read_plant(), C.POSTURE_RESTRICTED)

    run = world.schedule_run(world.lot_id, world.bay_id)
    assert run["run_state"] == C.RUN_STATE_SCHEDULED
    assert_close(
        world.read_plant()["emission_reserved_g"], 255.00, "emission_reserved_g", 2
    )

    world.set_clock("2026-09-02T06:00:00Z")
    validate_error(
        world.api.start_formation_run(run["id"], world.sup_a), E.ERR_PLANT_RESTRICTED
    )
    assert world.read_run(run["id"])["run_state"] == C.RUN_STATE_SCHEDULED
