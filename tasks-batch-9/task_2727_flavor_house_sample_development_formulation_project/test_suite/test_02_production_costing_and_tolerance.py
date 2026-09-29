"""Scale-up production costing and the per-component tolerance specification."""

from test_helpers.fixtures import (
    citrus_approved_formula,
    read_batch,
    request_scale_up_batch,
    set_batch_tolerance,
)


def test_fee_tier_is_chosen_from_the_pre_fee_material_cost(api):
    """The 12.0 percent tier is selected from 446550, before the fee exists.

    The PRD says "the compounding fee percentage is selected from that pre-fee
    material cost, once, and is never revisited: a `material_cost_cents` below
    500000 cents selects a `compounding_fee_pct` of 12.0".  For bench 2977 at
    target_kg 150 the material cost is 446550, so the rate is 12.0 and the fee
    is 53586.

    Design: Difficulty/combinatorial_formula/production_fee_tier_selected_from_pre_fee_material_cost
    """
    scenario = citrus_approved_formula(api)
    batch = request_scale_up_batch(api, scenario["formula"]["id"], target_kg=150)

    priced = set_batch_tolerance(api, batch["id"])

    assert priced["material_cost_cents"] == 446550
    assert float(priced["compounding_fee_pct"]) == 12.0
    assert priced["compounding_fee_cents"] == 53586
    assert priced["status"] == "TOLERANCE_SET"


def test_the_tier_survives_a_batch_total_that_crosses_the_tier_ceiling(api):
    """Adding the fee and the QA charge pushes the total past 500000 harmlessly.

    The PRD says "`batch_total_cents` is `material_cost_cents` plus
    `compounding_fee_cents` plus a flat QA release charge of 25000 cents" and
    that "a batch whose material cost sits just under a tier ceiling keeps the
    tier it selected even when adding the fee and the QA charge pushes
    `batch_total_cents` past that ceiling".  446550 + 53586 + 25000 is 525136,
    which is above 500000 while the rate stays 12.0.

    Design: Difficulty/combinatorial_formula/production_fee_tier_selected_from_pre_fee_material_cost
    """
    scenario = citrus_approved_formula(api)
    batch = request_scale_up_batch(api, scenario["formula"]["id"], target_kg=150)

    priced = set_batch_tolerance(api, batch["id"])

    assert priced["batch_total_cents"] == 525136
    assert priced["batch_total_cents"] > 500000
    assert float(priced["compounding_fee_pct"]) == 12.0
    assert priced["compounding_fee_cents"] != 35724
    assert priced["batch_total_cents"] != 507274


def test_production_cost_per_kg_rounds_the_batch_total_half_up(api):
    """525136 over 150 kilograms rounds half up to 3501 cents.

    The PRD says "`production_cost_per_kg_cents` is `batch_total_cents`
    divided by `target_kg`, rounded half up to whole cents", and that
    "rounding happens at exactly the first, third and fifth of those steps".
    525136 / 150 is 3500.9066..., so the stored figure is 3501.

    Design: Difficulty/combinatorial_formula/production_fee_tier_selected_from_pre_fee_material_cost
    """
    scenario = citrus_approved_formula(api)
    batch = request_scale_up_batch(api, scenario["formula"]["id"], target_kg=150)
    set_batch_tolerance(api, batch["id"])

    priced = read_batch(api, batch["id"])

    assert priced["production_cost_per_kg_cents"] == 3501
    assert priced["production_cost_per_kg_cents"] != 3500
    assert priced["material_cost_cents"] == 446550
    assert priced["batch_total_cents"] == 525136


def test_costing_fields_are_empty_until_the_tolerance_step_runs(api):
    """A REQUESTED batch carries no costing figures at all.

    The PRD says the batch "is created in `REQUESTED`" and "everything else is
    empty at creation: `material_cost_cents`, `compounding_fee_pct`,
    `compounding_fee_cents`, `batch_total_cents`,
    `production_cost_per_kg_cents` ... are all null, and `tolerance_spec` is
    an empty array".

    Design: Difficulty/combinatorial_formula/production_fee_tier_selected_from_pre_fee_material_cost
    """
    scenario = citrus_approved_formula(api)
    batch = request_scale_up_batch(api, scenario["formula"]["id"], target_kg=150)

    assert batch["status"] == "REQUESTED"
    assert batch["material_cost_cents"] is None
    assert batch["compounding_fee_pct"] is None
    assert batch["compounding_fee_cents"] is None
    assert batch["batch_total_cents"] is None
    assert batch["production_cost_per_kg_cents"] is None
    assert batch["tolerance_spec"] == []


def test_one_tolerance_call_emits_three_different_band_widths(api):
    """The four interacting inputs give 0.0300, 0.0200 and 1.0000 in one call.

    The PRD builds each band from "a relative band of two percent of the
    line's own `weight_pct`, floored at a minimum band of 0.0050 percent",
    times a potency factor where "a raw-material line whose material is
    `HIGH_IMPACT` takes 0.5 ... and any other raw-material line takes 1.0",
    times a scale factor where "from 100 up to but not including 1000 takes
    0.8", then "capped at a maximum band of 1.0000 percent".

    Design: Difficulty/combinatorial_formula/tolerance_band_nested_clamp_interaction
    """
    scenario = citrus_approved_formula(api)
    batch = request_scale_up_batch(api, scenario["formula"]["id"], target_kg=150)

    priced = set_batch_tolerance(api, batch["id"])
    spec = priced["tolerance_spec"]

    assert len(spec) == 3
    bands = [float(entry["band_pct"]) for entry in spec]
    assert bands == [0.03, 0.02, 1.0]
    assert len(set(bands)) == 3


def test_each_tolerance_entry_names_its_own_component_and_weight(api):
    """Entries come out in ascending sequence_no with the right band each.

    The PRD says "components are processed in ascending `sequence_no` order
    and one entry is emitted per component, each entry carrying the
    component's identifier as `component_id`, its `weight_pct` and the
    permitted `band_pct`".  The HIGH_IMPACT line at 3.7500 gets 0.0300, the
    standard line at 1.2500 gets 0.0200.

    Design: Difficulty/combinatorial_formula/tolerance_band_nested_clamp_interaction
    """
    scenario = citrus_approved_formula(api)
    c1, c2, c3 = scenario["components"]
    batch = request_scale_up_batch(api, scenario["formula"]["id"], target_kg=150)

    spec = set_batch_tolerance(api, batch["id"])["tolerance_spec"]
    by_component = {entry["component_id"]: entry for entry in spec}

    assert [entry["component_id"] for entry in spec] == [c1["id"], c2["id"], c3["id"]]
    assert float(by_component[c1["id"]]["weight_pct"]) == 3.75
    assert float(by_component[c1["id"]]["band_pct"]) == 0.03
    assert float(by_component[c2["id"]]["weight_pct"]) == 1.25
    assert float(by_component[c2["id"]]["band_pct"]) == 0.02


def test_the_maximum_band_clamp_beats_the_safety_headroom_on_the_solvent(api):
    """The 95 percent solvent line is clamped by 1.0000, not by its headroom.

    The PRD caps the geometric band "at a maximum band of 1.0000 percent" and
    computes the headroom band as "the material's `max_use_ppm` divided by
    10000 minus the line's `weight_pct`", taking "the smaller of the geometric
    band and the headroom band".  For PG-SOLV that headroom is 100.0000 -
    95.0000 = 5.0000 while the geometric band 1.5200 is clamped to 1.0000, so
    1.0000 wins.

    Design: Difficulty/combinatorial_formula/tolerance_band_nested_clamp_interaction
    """
    scenario = citrus_approved_formula(api)
    solvent_line = scenario["components"][2]
    batch = request_scale_up_batch(api, scenario["formula"]["id"], target_kg=150)

    spec = set_batch_tolerance(api, batch["id"])["tolerance_spec"]
    entry = next(item for item in spec if item["component_id"] == solvent_line["id"])

    assert float(entry["weight_pct"]) == 95.0
    assert float(entry["band_pct"]) == 1.0
    assert float(entry["band_pct"]) != 1.52
    assert float(entry["band_pct"]) != 5.0
