"""Immediate consistency: every derived field, parent ledger and computed read
already reflects a write by the time the very next request is served."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.assertions import (
    assert_close,
    assert_emission_ledger,
    assert_lead_balance,
    assert_posture,
    assert_run_energy,
)
from test_helpers.factories import abort_payload
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import validate_paginated, validate_success


def test_a_scheduled_run_moves_the_parent_ledger_before_the_next_request_is_served(
    formation_world: World,
):
    """The create body, the collection index, the parent ledger and the plant row all agree at once.

    "at scheduling the result is stored as `reserved_emission_g` and added to the plant's
    `emission_reserved_g` ... After a successful reservation the plant's `emission_utilization_ratio`
    and `compliance_posture` are re-derived in the same request." The ledger is defined as a live
    projection -- "`emission_reserved_g` is the sum of `reserved_emission_g` over the formation runs
    of this plant's lots whose `run_state` is either `SCHEDULED` or `CHARGING`" -- and the abort
    "releases the reservation with nothing consumed, returning the reserved-plus-consumed total to
    its pre-scheduling value". The lead ledger is untouched by any of it, and the quality summary
    "reports, as a string, the first of `ERR_LOT_STATE_INVALID`, `ERR_LOT_ENV_HELD`,
    `ERR_PLANT_FROZEN`, `ERR_SAMPLING_INCOMPLETE` and `ERR_ACCEPTANCE_EXCEEDED` that currently
    holds".

    Design: Corner/consistency_model/every_derived_field_and_ledger_is_visible_to_the_next_read_in_the_same_session
    """
    world = formation_world

    before = world.read_ledger()
    assert_emission_ledger(before, reserved_g=0.00, consumed_g=0.00, ratio=0.0000)
    opening_balance = world.read_mass_balance()
    assert_lead_balance(
        opening_balance, inventory_kg=10000.000, in_field_kg=0.000, recycled_kg=0.000
    )
    assert_close(
        opening_balance["lead_initial_inventory_kg"], 10000.000, "lead_initial_inventory_kg", 3
    )

    run = world.schedule_run(world.lot_id, world.bay_id)
    assert_run_energy(
        run,
        estimated_energy_kwh=102.00,
        provisional_charge_cents=2210,
        reserved_emission_g=255.00,
    )
    assert run["run_state"] == C.RUN_STATE_SCHEDULED

    rows, meta = validate_paginated(
        world.api.list_formation_runs(world.sup_a, {"lot_id": world.lot_id})
    )
    assert meta["total_count"] == 1, rows
    assert rows[0]["id"] == run["id"]
    assert rows[0]["run_state"] == C.RUN_STATE_SCHEDULED
    assert_close(rows[0]["reserved_emission_g"], 255.00, "reserved_emission_g", 2)

    reserved = world.read_ledger()
    assert_emission_ledger(reserved, reserved_g=255.00, consumed_g=0.00, ratio=0.0026)

    plant = world.read_plant()
    assert_posture(plant, C.POSTURE_OPEN)
    assert_close(plant["emission_reserved_g"], 255.00, "emission_reserved_g", 2)
    assert_close(
        plant["emission_utilization_ratio"], 0.0026, "emission_utilization_ratio", 4
    )
    assert_close(plant["emission_consumed_g"], 0.00, "emission_consumed_g", 2)

    aborted = validate_success(
        world.api.abort_formation_run(
            run["id"], abort_payload(C.ABORT_OPERATOR), world.sup_a
        ),
        200,
    )
    assert aborted["run_state"] == C.RUN_STATE_ABORTED
    assert aborted["provisional_charge_cents"] == 2210
    assert aborted["final_charge_cents"] == 0
    assert_close(aborted["consumed_emission_g"], 0.00, "consumed_emission_g", 2)
    assert aborted["metered_energy_kwh"] is None

    released = world.read_ledger()
    assert_emission_ledger(released, reserved_g=0.00, consumed_g=0.00, ratio=0.0000)
    assert_posture(world.read_plant(), C.POSTURE_OPEN)
    assert_lead_balance(
        world.read_mass_balance(),
        inventory_kg=10000.000,
        in_field_kg=0.000,
        recycled_kg=0.000,
    )
    assert world.read_plant()["formation_energy_charge_cents"] == 0

    summary = validate_success(
        world.api.get_quality_summary(world.lot_id, world.qa_a), 200
    )
    assert summary["sample_size"] is None
    assert summary["acceptance_number"] is None
    assert summary["sampling_plan_revision"] == 0
    assert summary["completed_test_count"] == 0
    assert summary["lot_capacity_yield_pct"] is None
    assert summary["release_blocked_by"] == E.ERR_LOT_STATE_INVALID
