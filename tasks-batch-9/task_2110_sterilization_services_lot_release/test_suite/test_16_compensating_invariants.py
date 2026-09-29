"""Compensating actions on two conserved quantities: the continuous abated
ethylene-oxide mass ledger and the discrete pallet count."""

import pytest

from test_helpers import (
    abort_cycle,
    add_load_position,
    api_client,
    assert_pallet_conservation,
    build_cycle_scenario,
    create_cycle,
    create_lot,
    create_product,
    create_qualified_qualification,
    get_cycle,
    get_lot,
    get_permit,
    operator,
    remove_load_position,
    setup_reference_data,
    start_cycle,
    validate_paginated,
)

WIDE_BAND_RECIPE = {
    "density_min_g_per_cm3": 0.0900,
    "density_max_g_per_cm3": 0.1100,
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 0,
}


def _running_cycle_at_exactly_the_allowance():
    env = build_cycle_scenario(
        stage="ready",
        modality="ETO",
        permit_overrides={"annual_allowance_kg": 48.0},
        cycle_overrides={"cycle_code": "C-A", "raw_eto_charge_kg": 1200.0},
    )
    start_cycle(env["cycle"]["id"])
    return env


def test_start_landing_exactly_on_the_allowance_suspends_the_permit():
    """PRD 3.6: "**Step three** is the allowance gate: if the prospective
    figure is strictly greater than the permit's `annual_allowance_kg` the
    start is refused with `ERR_PERMIT_ALLOWANCE_EXCEEDED`, while landing
    exactly on the allowance is accepted."
    PRD 3.6: "If the commit leaves `consumed_kg_ytd` at or above
    `annual_allowance_kg`, the permit moves `ACTIVE → SUSPENDED` on the spot,
    and every subsequent start beneath it is refused with
    `ERR_PERMIT_NOT_ACTIVE` until an abort or an administrator restores it."

    Design: Difficulty/compensating_invariant/abort_restores_abated_eto_mass_ledger_and_reinstates_permit
    """
    env = _running_cycle_at_exactly_the_allowance()

    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "RUNNING"
    assert cycle["abated_eto_kg"] == pytest.approx(48.000, abs=1e-6)
    assert cycle["emission_fee_usd"] == pytest.approx(576.00, abs=0.001)

    permit = get_permit(env["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(48.000, abs=1e-6)
    assert permit["total_emission_fee_usd"] == pytest.approx(576.00, abs=0.001)
    assert permit["status"] == "SUSPENDED"


def test_abort_credits_back_the_stored_mass_and_reinstates_the_permit():
    """PRD 3.6: "From `RUNNING` the abort additionally performs the
    compensating half of the emission ledger: the permit's `consumed_kg_ytd`
    becomes its current value less exactly the cycle's stored `abated_eto_kg`,
    rounded half up to three decimal places, and its `total_emission_fee_usd`
    becomes its current value less exactly the cycle's stored
    `emission_fee_usd`, rounded half up to two decimal places."
    PRD 3.6: "If that credit leaves `consumed_kg_ytd` strictly below
    `annual_allowance_kg` and the permit is currently `SUSPENDED`, the permit
    walks `SUSPENDED → ACTIVE`."
    PRD 3.6: "The cycle's own `abated_eto_kg` and `emission_fee_usd` are then
    zeroed, its positions removed on the same terms as above, and the lots it
    was processing walk `IN_PROCESS → RECEIVED` — back to the receiving dock,
    not to `STAGED`, because the abort has dissolved their load map."

    Design: Difficulty/compensating_invariant/abort_restores_abated_eto_mass_ledger_and_reinstates_permit
    """
    env = _running_cycle_at_exactly_the_allowance()

    aborted = abort_cycle(env["cycle"]["id"], reason="chamber pressure alarm during dwell")

    assert aborted["status"] == "CANCELLED"
    assert aborted["abated_eto_kg"] == pytest.approx(0.0, abs=1e-9)
    assert aborted["emission_fee_usd"] == pytest.approx(0.0, abs=1e-9)
    assert aborted["loaded_pallet_count"] == 0
    assert aborted["load_density_g_per_cm3"] == pytest.approx(0.0, abs=1e-9)

    permit = get_permit(env["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(0.0, abs=1e-9)
    assert permit["total_emission_fee_usd"] == pytest.approx(0.0, abs=1e-9)
    assert permit["status"] == "ACTIVE"

    lot = get_lot(env["lot"]["id"])
    assert lot["status"] == "RECEIVED"
    assert lot["staged_pallet_count"] == 0
    assert lot["available_pallet_count"] == 2
    assert_pallet_conservation(lot)

    _, meta = validate_paginated(
        api_client.list_load_positions(operator(), params={"cycle_id": env["cycle"]["id"]})
    )
    assert meta["total_count"] == 0


def _loading_cycle_with_two_lots():
    env = setup_reference_data(recipe_overrides=WIDE_BAND_RECIPE)
    product_b = create_product(
        env["customer"]["id"], product_code="P2", pallet_mass_kg=90.0, pallet_volume_m3=0.8
    )
    create_qualified_qualification(product_b["id"], env["recipe"]["id"])
    lot_a = create_lot(
        env["customer"]["id"], env["product"]["id"], lot_code="L-P1", total_pallet_count=4
    )
    lot_b = create_lot(
        env["customer"]["id"], product_b["id"], lot_code="L-P2", total_pallet_count=2
    )
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"])
    position_a = add_load_position(
        cycle["id"], lot_a["id"], position_index=1, zone="MIN_DOSE", pallet_count=2
    )
    position_b = add_load_position(
        cycle["id"], lot_b["id"], expected_cycle_version=position_a["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=1,
    )
    env.update(
        {
            "lot_a": lot_a,
            "lot_b": lot_b,
            "cycle": cycle,
            "position_a": position_a,
            "position_b": position_b,
        }
    )
    return env


def test_removing_one_slot_returns_its_pallets_to_the_lot():
    """PRD 3.5: "The row is hard-deleted — there is no soft-delete or
    tombstone — and the same arithmetic runs in reverse: the cycle's
    `loaded_pallet_count` falls by the removed `pallet_count`,
    `load_density_g_per_cm3` is recomputed, the lot's `staged_pallet_count`
    falls and `available_pallet_count` is refreshed, and the lot walks `STAGED
    → RECEIVED` when it retains no load position on any cycle anywhere."
    PRD 2.9: "For every lot, `staged_pallet_count` plus
    `available_pallet_count` always equals `total_pallet_count`, and
    `staged_pallet_count` always equals the sum of `pallet_count` over every
    load position that references that lot."

    Design: Difficulty/compensating_invariant/delete_load_position_conserves_pallet_count_across_lot_and_cycle
    """
    env = _loading_cycle_with_two_lots()
    before = get_cycle(env["cycle"]["id"])
    assert before["loaded_pallet_count"] == 3
    assert before["load_density_g_per_cm3"] == pytest.approx(0.1031, abs=1e-9)

    response = remove_load_position(env["cycle"]["id"], env["position_b"]["id"])
    assert response.status_code == 204, "removing a slot returns 204 with no body"

    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["loaded_pallet_count"] == 2
    assert cycle["load_density_g_per_cm3"] == pytest.approx(0.1000, abs=1e-9)

    lot_b = get_lot(env["lot_b"]["id"])
    assert lot_b["staged_pallet_count"] == 0
    assert lot_b["available_pallet_count"] == 2
    assert lot_b["status"] == "RECEIVED"
    assert_pallet_conservation(lot_b)

    lot_a = get_lot(env["lot_a"]["id"])
    assert lot_a["staged_pallet_count"] == 2
    assert lot_a["available_pallet_count"] == 2
    assert lot_a["status"] == "STAGED"
    assert_pallet_conservation(lot_a)


def test_removing_the_last_slot_returns_the_cycle_to_planned():
    """PRD 3.5: "A cycle that was `READY` reverts to `LOADING`; a cycle already
    in `LOADING` that still retains at least one other position holds at
    `LOADING → LOADING`; a cycle left with no positions at all goes `LOADING →
    PLANNED` with `loaded_pallet_count` at 0 and `load_density_g_per_cm3` at
    0.0000."

    Design: Difficulty/compensating_invariant/delete_load_position_conserves_pallet_count_across_lot_and_cycle
    """
    env = _loading_cycle_with_two_lots()

    remove_load_position(env["cycle"]["id"], env["position_b"]["id"])
    assert get_cycle(env["cycle"]["id"])["status"] == "LOADING"

    remove_load_position(env["cycle"]["id"], env["position_a"]["id"])

    cycle = get_cycle(env["cycle"]["id"])
    assert cycle["status"] == "PLANNED"
    assert cycle["loaded_pallet_count"] == 0
    assert cycle["load_density_g_per_cm3"] == pytest.approx(0.0, abs=1e-9)

    lot_a = get_lot(env["lot_a"]["id"])
    assert lot_a["staged_pallet_count"] == 0
    assert lot_a["available_pallet_count"] == 4
    assert lot_a["status"] == "RECEIVED"
    assert_pallet_conservation(lot_a)

    _, meta = validate_paginated(
        api_client.list_load_positions(operator(), params={"cycle_id": env["cycle"]["id"]})
    )
    assert meta["total_count"] == 0
