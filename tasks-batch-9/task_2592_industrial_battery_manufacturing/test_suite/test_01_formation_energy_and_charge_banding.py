"""Formation-run energy estimation, tariff banding and the emission quota."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import (
    assert_close,
    assert_emission_ledger,
    assert_posture,
    assert_run_energy,
    assert_run_state,
)
from test_helpers.factories import abort_payload, formation_run_payload
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def test_scheduling_prices_the_provisional_nameplate_variant(formation_world: World):
    """The provisional estimate is the nameplate cap, banded over the scheduled window.

    "The nameplate figure is the bay's `rated_power_kw` multiplied by the scheduled
    window's duration in hours, multiplied by a bay utilization factor of 0.85 --
    rectifiers are never assumed to run flat out." For a 20.00 kW bay over the six-hour
    window 06:00Z-12:00Z that is 102.00 kWh, which binds below the theoretical figure of
    9 * 12 * 465.0 * 2.0 * 1.5 / 1000 = 150.66 kWh, and the scheduled window carries four
    peak hours (08:00-12:00) and two off-peak hours.

    Design: Difficulty/dual_variant_calc/formation_energy_provisional_nameplate_vs_final_metered
    """
    world = formation_world
    run = world.schedule_run(world.lot_id, world.bay_id)

    assert_run_energy(
        run,
        estimated_energy_kwh=102.00,
        peak_hours=4.0000,
        offpeak_hours=2.0000,
        provisional_charge_cents=2210,
        reserved_emission_g=255.00,
    )
    assert_run_state(run, C.RUN_STATE_SCHEDULED)
    assert run["metered_energy_kwh"] is None
    assert_close(run["charge_factor_used"], 1.5, "charge_factor_used", 2)


def test_completion_reprices_on_the_metered_variant_and_actual_window(formation_world: World):
    """The final variant swaps in the metered energy and the actual window.

    "the energy is the metered reading rather than the nameplate-capped estimate, and the
    band split is taken over the *actual* window running from `actual_start_at` up to
    `actual_end_at`, producing `actual_peak_hours` and `actual_offpeak_hours` at four
    decimal places." A run quoted for 06:00Z-12:00Z but actually run 05:00Z-13:00Z carries
    three off-peak and five peak hours, and 100.00 metered kWh splits 62.50 / 37.50, priced
    per band as 1563 + 563 = 2126 cents.

    Design: Difficulty/dual_variant_calc/formation_energy_provisional_nameplate_vs_final_metered
    """
    world = formation_world
    run = world.schedule_run(world.lot_id, world.bay_id)
    assert_run_energy(run, estimated_energy_kwh=102.00, provisional_charge_cents=2210)

    world.set_clock("2026-09-02T05:00:00Z")
    validate_success(
        world.api.start_formation_run(
            run["id"], world.sup_a, payload={"actual_start_at": "2026-09-02T05:00:00Z"}
        ),
        200,
    )
    world.set_clock("2026-09-02T13:00:00Z")
    completed = world.complete_run(
        run["id"],
        metered_energy_kwh=100.00,
        formation_capacity_pct=95.00,
        actual_end_at="2026-09-02T13:00:00Z",
    )

    assert_run_state(completed, C.RUN_STATE_COMPLETED)
    assert_close(completed["actual_peak_hours"], 5.0000, "actual_peak_hours", 4)
    assert_close(completed["actual_offpeak_hours"], 3.0000, "actual_offpeak_hours", 4)
    assert completed["final_charge_cents"] == 2126, completed["final_charge_cents"]
    assert_close(completed["consumed_emission_g"], 250.00, "consumed_emission_g", 2)
    assert completed["capacity_validation_result"] == C.CAPACITY_RESULT_PASS

    plant = world.read_plant()
    assert plant["formation_energy_charge_cents"] == 2126
    assert_emission_ledger(world.read_ledger(), reserved_g=0.00, consumed_g=250.00)


def test_each_tariff_band_is_rounded_to_whole_cents_before_the_two_are_added(
    formation_world: World,
):
    """Per-band rounding yields 2126 cents where sum-then-round would yield 2125.

    "Each band is priced and rounded to whole cents *first*, and only then are the two
    whole-cent amounts added". 62.50 peak kWh at 25 cents is 1562.50 -> 1563 and 37.50
    off-peak kWh at 15 cents is 562.50 -> 563, so the charge is 2126; adding the two band
    products first and rounding once would give 2125, which the requirements explicitly
    reject.

    Design: Difficulty/combinatorial_formula/formation_charge_per_band_rounding_order_mode_b
    """
    world = formation_world
    run = world.schedule_run(world.lot_id, world.bay_id)
    world.set_clock("2026-09-02T05:00:00Z")
    validate_success(
        world.api.start_formation_run(
            run["id"], world.sup_a, payload={"actual_start_at": "2026-09-02T05:00:00Z"}
        ),
        200,
    )
    world.set_clock("2026-09-02T13:00:00Z")
    completed = world.complete_run(
        run["id"],
        metered_energy_kwh=100.00,
        formation_capacity_pct=92.00,
        actual_end_at="2026-09-02T13:00:00Z",
    )

    assert completed["final_charge_cents"] == 2126, completed["final_charge_cents"]
    assert completed["final_charge_cents"] != 2125
    assert_close(completed["actual_peak_hours"], 5.0000, "actual_peak_hours", 4)
    assert_close(completed["actual_offpeak_hours"], 3.0000, "actual_offpeak_hours", 4)
    assert completed["capacity_validation_result"] == C.CAPACITY_RESULT_PASS
    assert world.read_plant()["formation_energy_charge_cents"] == 2126


def test_per_band_rounding_holds_for_a_second_pair_of_half_cent_products(
    formation_world: World,
):
    """A different metered reading lands on a half cent in both bands and still rounds up twice.

    "the peak energy multiplied by the plant's `peak_tariff_cents_per_kwh` is rounded half
    up to a whole cent, the off-peak energy multiplied by the plant's
    `offpeak_tariff_cents_per_kwh` is rounded half up to a whole cent, and the charge is the
    sum of those two rounded values." For 60.00 metered kWh over the same five-peak /
    three-off-peak window the bands are 37.50 and 22.50 kWh, priced 937.50 -> 938 and
    337.50 -> 338 for a total of 1276 rather than the 1275 of the rejected order.

    Design: Difficulty/combinatorial_formula/formation_charge_per_band_rounding_order_mode_b
    """
    world = formation_world
    run = world.schedule_run(world.lot_id, world.bay_id)
    world.set_clock("2026-09-02T05:00:00Z")
    validate_success(
        world.api.start_formation_run(
            run["id"], world.sup_a, payload={"actual_start_at": "2026-09-02T05:00:00Z"}
        ),
        200,
    )
    world.set_clock("2026-09-02T13:00:00Z")
    completed = world.complete_run(
        run["id"],
        metered_energy_kwh=60.00,
        formation_capacity_pct=95.00,
        actual_end_at="2026-09-02T13:00:00Z",
    )

    assert completed["final_charge_cents"] == 1276, completed["final_charge_cents"]
    assert completed["final_charge_cents"] != 1275
    assert_close(completed["consumed_emission_g"], 150.00, "consumed_emission_g", 2)
    assert world.read_plant()["formation_energy_charge_cents"] == 1276


def test_reservation_landing_exactly_on_ratio_one_is_accepted_and_freezes_the_plant(
    make_world,
):
    """A permit of exactly 255.00 g admits the 255.00 g reservation and freezes the plant.

    "A reservation that lands exactly on 1.0000 is **accepted** and immediately freezes the
    plant through the posture recompute; only a result strictly above 1.0000 is refused,
    with `ERR_EMISSION_BUDGET_EXCEEDED`." The very request the quota allows therefore closes
    the plant, so the next scheduling attempt on a second bay and a second lot is refused by
    the freeze rather than by the quota.

    Design: Difficulty/boundary_precision_check/emission_ratio_exactly_one_is_accepted_then_freezes
    """
    world = make_world(plant_overrides={"monthly_lead_emission_permit_g": 255.00})
    bay1 = world.add_bay("BAY-1")
    bay2 = world.add_bay("BAY-2")
    lot_e = world.lot_in_state(C.LOT_FORMATION, "LOT-E", 9)
    lot_f = world.lot_in_state(C.LOT_FORMATION, "LOT-F", 9)

    run = world.schedule_run(lot_e["id"], bay1)
    assert_run_energy(run, estimated_energy_kwh=102.00, reserved_emission_g=255.00)
    assert_run_state(run, C.RUN_STATE_SCHEDULED)

    plant = world.read_plant()
    assert_close(plant["emission_reserved_g"], 255.00, "emission_reserved_g", 2)
    assert_close(plant["emission_utilization_ratio"], 1.0000, "emission_utilization_ratio", 4)
    assert_posture(plant, C.POSTURE_FROZEN)

    refused = world.api.create_formation_run(
        formation_run_payload(
            lot_f["id"], bay2, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"
        ),
        world.sup_a,
    )
    validate_error(refused, E.ERR_PLANT_FROZEN)


def test_one_hundredth_of_a_gram_below_the_permit_refuses_the_same_reservation(make_world):
    """A permit of 254.99 g pushes the same 255.00 g reservation strictly above 1.0000.

    "Before the reservation is accepted the quota is checked: the plant's
    `emission_reserved_g` plus its `emission_consumed_g` plus this run's
    `reserved_emission_g`, divided by `monthly_lead_emission_permit_g`, must be at most
    1.0000." With a 254.99 g permit the quotient exceeds one, the run is refused and nothing
    is booked against the plant.

    Design: Difficulty/boundary_precision_check/emission_ratio_exactly_one_is_accepted_then_freezes
    """
    world = make_world(plant_overrides={"monthly_lead_emission_permit_g": 254.99})
    bay = world.add_bay("BAY-1")
    lot = world.lot_in_state(C.LOT_FORMATION, "LOT-E", 9)

    refused = world.api.create_formation_run(
        formation_run_payload(
            lot["id"], bay, "2026-09-02T06:00:00Z", "2026-09-02T12:00:00Z"
        ),
        world.sup_a,
    )
    validate_error(refused, E.ERR_EMISSION_BUDGET_EXCEEDED)

    plant = world.read_plant()
    assert_close(plant["emission_reserved_g"], 0.00, "emission_reserved_g", 2)
    assert_posture(plant, C.POSTURE_OPEN)
    rows, _ = validate_paginated(world.api.list_formation_runs(world.admin))
    assert rows == [], rows


def test_completion_moves_the_reservation_into_consumption_in_one_write(
    formation_world: World,
):
    """Completing a run releases the reservation and books the consumption and the money.

    "Completion settles three ledgers in one write: the plant's `emission_reserved_g`
    decreases by this run's `reserved_emission_g`, its `emission_consumed_g` increases by
    this run's `consumed_emission_g`, and its `formation_energy_charge_cents` increases by
    `final_charge_cents`." Metering exactly 100.00 kWh over the scheduled 06:00Z-12:00Z
    window bands 66.67 / 33.33 kWh for 1667 + 500 = 2167 cents and consumes 250.00 g against
    a 100000.00 g permit, a utilization ratio of 0.0025.

    Design: Difficulty/compensating_invariant/invariant_e1_emission_reservation_released_by_abort_and_by_completion
    """
    world = formation_world
    run = world.schedule_run(world.lot_id, world.bay_id)
    assert_run_energy(run, reserved_emission_g=255.00)

    world.set_clock("2026-09-02T06:00:00Z")
    world.start_run(run["id"])
    world.set_clock("2026-09-02T12:00:00Z")
    completed = world.complete_run(
        run["id"], metered_energy_kwh=100.00, formation_capacity_pct=95.00
    )

    assert completed["final_charge_cents"] == 2167, completed["final_charge_cents"]
    assert_close(completed["consumed_emission_g"], 250.00, "consumed_emission_g", 2)
    assert_emission_ledger(
        world.read_ledger(), reserved_g=0.00, consumed_g=250.00, ratio=0.0025
    )
    plant = world.read_plant()
    assert plant["formation_energy_charge_cents"] == 2167
    assert_posture(plant, C.POSTURE_OPEN)


def test_abort_releases_the_reservation_in_full_with_nothing_consumed_or_charged(
    formation_world: World,
):
    """An aborted run gives its grams back and never touches the plant's money.

    "The run moves to `ABORTED`, `actual_end_at` is stamped from the logical clock, and the
    reservation is released in full with nothing consumed and nothing charged:
    `final_charge_cents` and `consumed_emission_g` stay 0 and `metered_energy_kwh` stays
    null." A second run scheduled 14:00Z-20:00Z is quoted 2550 cents against 255.00 reserved
    grams, and after the abort the plant's ledger is exactly what the earlier completion left
    behind.

    Design: Difficulty/compensating_invariant/invariant_e1_emission_reservation_released_by_abort_and_by_completion
    """
    world = formation_world
    first = world.schedule_run(world.lot_id, world.bay_id)
    world.set_clock("2026-09-02T06:00:00Z")
    world.start_run(first["id"])
    world.set_clock("2026-09-02T12:00:00Z")
    world.complete_run(first["id"], metered_energy_kwh=100.00, formation_capacity_pct=95.00)

    second = world.schedule_run(
        world.lot_id, world.bay_id, "2026-09-02T14:00:00Z", "2026-09-02T20:00:00Z"
    )
    assert second["provisional_charge_cents"] == 2550, second["provisional_charge_cents"]
    assert_close(second["reserved_emission_g"], 255.00, "reserved_emission_g", 2)
    assert_close(world.read_plant()["emission_reserved_g"], 255.00, "emission_reserved_g", 2)

    world.set_clock("2026-09-02T14:00:00Z")
    world.start_run(second["id"])
    world.set_clock("2026-09-02T16:00:00Z")
    aborted = validate_success(
        world.api.abort_formation_run(
            second["id"], abort_payload(C.ABORT_BAY_FAULT), world.sup_a
        ),
        200,
    )

    assert_run_state(aborted, C.RUN_STATE_ABORTED)
    assert aborted["metered_energy_kwh"] is None
    assert aborted["final_charge_cents"] == 0
    assert_close(aborted["consumed_emission_g"], 0.00, "consumed_emission_g", 2)
    assert aborted["provisional_charge_cents"] == 2550

    assert_emission_ledger(world.read_ledger(), reserved_g=0.00, consumed_g=250.00)
    plant = world.read_plant()
    assert plant["formation_energy_charge_cents"] == 2167
    assert_posture(plant, C.POSTURE_OPEN)
