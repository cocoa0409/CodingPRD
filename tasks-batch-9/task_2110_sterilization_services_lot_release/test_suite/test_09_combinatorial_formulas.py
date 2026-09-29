"""Combinatorial formulas whose evaluation order changes the answer.

The aggregate load density must accumulate first and round once; the emission
fee must select its rate band from the consumption figure that already
includes the charge being priced.
"""

import pytest

from test_helpers import (
    add_load_position,
    build_cycle_scenario,
    create_cycle,
    create_lot,
    create_qualified_qualification,
    create_product,
    get_cycle,
    get_permit,
    place_indicator,
    setup_reference_data,
    sign_ready,
    start_cycle,
)

MIXED_BAND_RECIPE = {
    "density_min_g_per_cm3": 0.1000,
    "density_max_g_per_cm3": 0.1060,
    "required_min_zone_dosimeters": 1,
    "required_routine_dosimeters": 1,
    "required_biological_indicators": 0,
}


def _setup_mixed_density_cycle():
    """One cycle holding one pallet of a 120.0 kg / 1.2 m3 product and one
    pallet of a 90.0 kg / 0.8 m3 product."""
    env = setup_reference_data(recipe_overrides=MIXED_BAND_RECIPE)
    product_b = create_product(
        env["customer"]["id"],
        product_code="P2",
        pallet_mass_kg=90.0,
        pallet_volume_m3=0.8,
    )
    create_qualified_qualification(product_b["id"], env["recipe"]["id"])
    lot_a = create_lot(
        env["customer"]["id"], env["product"]["id"], lot_code="L-P1", total_pallet_count=1
    )
    lot_b = create_lot(
        env["customer"]["id"], product_b["id"], lot_code="L-P2", total_pallet_count=1
    )
    cycle = create_cycle(env["chamber"]["id"], env["recipe"]["id"], cycle_code="C-MIX")
    env.update({"product_b": product_b, "lot_a": lot_a, "lot_b": lot_b, "cycle": cycle})
    return env


def test_load_density_accumulates_then_rounds_once():
    """PRD 3.5: "the server accumulates a total mass in grams by multiplying
    each position's `pallet_count` by the `pallet_mass_kg` of the product
    behind that position's lot and then by one thousand to convert kilograms to
    grams, and accumulates a total volume in cubic centimetres by multiplying
    each position's `pallet_count` by that product's `pallet_volume_m3` and
    then by one million to convert cubic metres to cubic centimetres."
    PRD 3.5: "The total mass is then divided by the total volume exactly once,
    and that single quotient is rounded half up to four decimal places to give
    `load_density_g_per_cm3`."
    PRD 3.5: "Rounding each position's own density to four places and averaging
    those per-position figures is explicitly **not** the rule, and produces a
    different answer for any load whose positions differ in volume."

    Design: Difficulty/combinatorial_formula/load_density_sum_then_round_not_per_position_round_then_average
    """
    env = _setup_mixed_density_cycle()

    first = add_load_position(
        env["cycle"]["id"], env["lot_a"]["id"], position_index=1, zone="MIN_DOSE",
        pallet_count=1,
    )
    after_first = get_cycle(env["cycle"]["id"])
    assert after_first["load_density_g_per_cm3"] == pytest.approx(0.1000, abs=1e-9), (
        "one pallet of 120.0 kg over 1.2 m3 is exactly 0.1000 g/cm3"
    )

    add_load_position(
        env["cycle"]["id"], env["lot_b"]["id"],
        expected_cycle_version=first["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=1,
    )
    cycle = get_cycle(env["cycle"]["id"])

    assert cycle["load_density_g_per_cm3"] == pytest.approx(0.1050, abs=1e-9), (
        "210000 g over 2000000 cm3 rounds once to 0.1050"
    )
    assert cycle["load_density_g_per_cm3"] != pytest.approx(0.1063, abs=1e-9), (
        "0.1063 is the rejected round-each-position-then-average answer"
    )
    assert cycle["loaded_pallet_count"] == 2


def test_ready_sign_off_accepts_the_pinned_aggregate_density():
    """PRD 3.6: "Third, the cycle's `load_density_g_per_cm3` must sit inside
    the recipe's validated band — at or above `density_min_g_per_cm3` and
    strictly below `density_max_g_per_cm3` — with a density below the floor or
    at or above the ceiling refused as `ERR_LOAD_DENSITY_OUT_OF_BAND`."
    PRD 3.6: "On success the cycle moves `LOADING → READY` and its `version`
    increases by one, which invalidates any load-map handle a client was
    holding."

    Design: Difficulty/combinatorial_formula/load_density_sum_then_round_not_per_position_round_then_average
    """
    env = _setup_mixed_density_cycle()
    first = add_load_position(
        env["cycle"]["id"], env["lot_a"]["id"], position_index=1, zone="MIN_DOSE",
        pallet_count=1,
    )
    second = add_load_position(
        env["cycle"]["id"], env["lot_b"]["id"],
        expected_cycle_version=first["cycle_version_after"],
        position_index=2, zone="INTERIOR", pallet_count=1,
    )
    place_indicator(
        first["id"], indicator_type="DOSIMETER", placement_zone="MIN_DOSE",
        serial_code="D-MIN",
    )
    place_indicator(
        second["id"], indicator_type="DOSIMETER", placement_zone="ROUTINE",
        serial_code="D-RT",
    )

    ready = sign_ready(env["cycle"]["id"])

    assert ready["status"] == "READY", (
        "0.1050 sits inside [0.1000, 0.1060); the rejected 0.1063 would not"
    )
    assert ready["load_density_g_per_cm3"] == pytest.approx(0.1050, abs=1e-9)
    assert ready["loaded_pallet_count"] == 2


def test_first_eto_charge_prices_in_the_lowest_rate_band():
    """PRD 3.6: "**Step one** computes the abated mass: the cycle's
    `raw_eto_charge_kg` multiplied by the fraction of gas that survives
    abatement — one minus the chamber's `abatement_efficiency_pct` divided by
    one hundred — with the result rounded half up to three decimal places."
    PRD 3.2: "When that figure is at most 50.000 kilograms, the rate is 12.00
    US dollars per abated kilogram."
    PRD 3.6: "**Step six** commits: the permit's `consumed_kg_ytd` becomes the
    prospective figure, the permit's `total_emission_fee_usd` becomes its
    previous value plus the new fee rounded half up to two decimal places, and
    the cycle's `abated_eto_kg` records the abated mass."

    Design: Difficulty/combinatorial_formula/emission_fee_tier_keyed_on_post_charge_ytd_not_pre_charge
    """
    env = build_cycle_scenario(
        stage="ready",
        modality="ETO",
        lot_overrides={"lot_code": "L-A"},
        cycle_overrides={"cycle_code": "C-A", "raw_eto_charge_kg": 1200.0},
    )

    started = start_cycle(env["cycle"]["id"])

    assert started["abated_eto_kg"] == pytest.approx(48.000, abs=1e-6), (
        "1200.0 kg at 96.0 percent abatement leaves 48.000 kg"
    )
    assert started["emission_fee_usd"] == pytest.approx(576.00, abs=0.001), (
        "48.000 kg at the 12.00 rate is 576.00"
    )
    permit = get_permit(env["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(48.000, abs=1e-6)
    assert permit["total_emission_fee_usd"] == pytest.approx(576.00, abs=0.001)
    assert permit["status"] == "ACTIVE"


def test_emission_fee_rate_band_comes_from_the_post_charge_consumption():
    """PRD 3.6: "**Step four** selects the rate from the three-band schedule of
    §3.2 using the *prospective* figure, not the pre-charge one — 12.00 dollars
    per kilogram at or below 50.000 kilograms, 18.50 dollars per kilogram above
    50.000 and at or below 200.000, and 27.00 dollars per kilogram above
    200.000."
    PRD 3.6: "**Step five** computes `emission_fee_usd` as the abated mass
    multiplied by that rate, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/emission_fee_tier_keyed_on_post_charge_ytd_not_pre_charge
    """
    env = build_cycle_scenario(
        stage="ready",
        modality="ETO",
        lot_overrides={"lot_code": "L-A"},
        cycle_overrides={"cycle_code": "C-A", "raw_eto_charge_kg": 1200.0},
    )
    start_cycle(env["cycle"]["id"])
    assert get_permit(env["permit"]["id"])["consumed_kg_ytd"] == pytest.approx(
        48.000, abs=1e-6
    )

    second = build_cycle_scenario(
        stage="ready",
        modality="ETO",
        env=env,
        lot_overrides={"lot_code": "L-B"},
        cycle_overrides={
            "cycle_code": "C-B",
            "scheduled_start_at": "2026-08-11T07:00:00Z",
            "scheduled_end_at": "2026-08-11T13:00:00Z",
            "raw_eto_charge_kg": 100.0,
        },
    )

    started = start_cycle(second["cycle"]["id"])

    assert started["abated_eto_kg"] == pytest.approx(4.000, abs=1e-6)
    assert started["emission_fee_usd"] == pytest.approx(74.00, abs=0.001), (
        "the prospective 52.000 kg selects the 18.50 rate: 4.000 * 18.50 == 74.00"
    )
    assert started["emission_fee_usd"] != pytest.approx(48.00, abs=0.001), (
        "48.00 is the answer produced by pricing off the pre-charge 48.000 kg"
    )
    permit = get_permit(env["permit"]["id"])
    assert permit["consumed_kg_ytd"] == pytest.approx(52.000, abs=1e-6)
    assert permit["total_emission_fee_usd"] == pytest.approx(650.00, abs=0.001)
    assert permit["status"] == "ACTIVE"
