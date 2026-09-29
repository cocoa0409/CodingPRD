"""Formulas whose factors must interact, not merely add.

The excursion risk index of PRD 3.7 combines four inputs with a clamp between
them, and the component demand of PRD 3.5 pins the order of a ceiling and a sum.
Both break visibly if the operations are reordered.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import assertions, constants, fixtures
from test_helpers.test_users import MICROBIOLOGY_ANALYST, PROGRAM_MANAGER

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: em_excursion_risk_index_four_factor_interaction
# ---------------------------------------------------------------------------
def _three_excursions(api) -> Json:
    """A filling batch plus one excursion of each sample type in a grade B suite."""
    program = fixtures.build_program(api, stage=fixtures.STAGE_FILLING)
    air = fixtures.record_em_sample(
        api,
        program["suite_id"],
        sample_type="VIABLE_AIR",
        cfu_count=20,
        batch_order_id=program["batch_id"],
    )
    surface = fixtures.record_em_sample(
        api, program["suite_id"], sample_type="SURFACE", cfu_count=20
    )
    glove = fixtures.record_em_sample(
        api, program["suite_id"], sample_type="PERSONNEL_GLOVE", cfu_count=5
    )
    program.update({"air": air, "surface": surface, "glove": glove})
    return program


def test_risk_index_reflects_all_four_factors_on_three_excursions(api):
    """Ratio, grade weight, sample-type surcharge and batch exposure all show up.

    PRD 3.7: "The sample-type surcharge is 25 points for a `PERSONNEL_GLOVE` sample, 10 points for a `SURFACE` sample and 0 for `VIABLE_AIR` — a contaminated glove print is the most damning finding available."

    Design: Difficulty/combinatorial_formula/em_excursion_risk_index_four_factor_interaction
    """
    world = _three_excursions(api)

    air, surface, glove = world["air"], world["surface"], world["glove"]

    assert (air["alert_limit"], air["action_limit"]) == (5, 10)
    assert air["classification"] == "ACTION"
    assert air["risk_index"] == 100

    assert (surface["alert_limit"], surface["action_limit"]) == (3, 5)
    assert surface["classification"] == "ACTION"
    assert surface["risk_index"] == 110

    assert (glove["alert_limit"], glove["action_limit"]) == (1, 5)
    assert glove["classification"] == "ACTION"
    assert glove["risk_index"] == 65

    assertions.assert_em_sample_classification(air, "B", batch_was_filling=True)
    assertions.assert_em_sample_classification(surface, "B")
    assertions.assert_em_sample_classification(glove, "B")


def test_risk_index_clamps_the_core_term_before_the_surcharges_join_it(api):
    """A surface excursion at four times its action limit still lands on 110.

    PRD 3.7: "The rounding happens on the core term alone and before the surcharges join it; the surcharges are never rounded and the overall cap is applied last."

    Design: Difficulty/combinatorial_formula/em_excursion_risk_index_four_factor_interaction
    """
    world = _three_excursions(api)

    surface = fixtures.read_em_sample(api, world["surface"]["id"], MICROBIOLOGY_ANALYST)
    assert surface["risk_index"] == constants.RISK_INDEX_CORE_CEILING + 10
    assert surface["risk_index"] < constants.RISK_INDEX_CAP

    air = fixtures.read_em_sample(api, world["air"]["id"], MICROBIOLOGY_ANALYST)
    assert air["investigation_status"] == "OPEN"

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["open_action_excursion_count"] == 3
    assert suite["posture"] == constants.POSTURE_RESTRICTED

    batch = fixtures.read_batch(api, world["batch_id"])
    assert batch["production_status"] == "FILLING"


# ---------------------------------------------------------------------------
# Design instance: component_demand_per_line_rounding_then_sum
# ---------------------------------------------------------------------------
def _two_presentations(api) -> Json:
    """One suite, one VIAL project and one PRESYRINGE project, one batch each."""
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api, suite_code="FS-1", grade="B")
    media_fill = fixtures.create_media_fill(api, suite["id"])
    fixtures.execute_media_fill(
        api, media_fill["id"], units_filled=6000, participating_operator_names=["OP-A"]
    )
    fixtures.read_media_fill_out(api, media_fill["id"], 0)
    pq_a = fixtures.create_qualification(
        api, "OP-A", suite["id"], media_fill_id=media_fill["id"]
    )
    fixtures.qualify(api, pq_a["id"])

    vial_project = fixtures.create_project(
        api,
        suite["id"],
        client_name="Sponsor A",
        molecule_name="MOL-A",
        dosage_form="VIAL",
        reserved_unit_budget=30000,
    )
    fixtures.activate_project(api, vial_project["id"])
    syringe_project = fixtures.create_project(
        api,
        suite["id"],
        client_name="Sponsor C",
        molecule_name="MOL-C",
        dosage_form="PRESYRINGE",
        target_fill_weight_mg=500,
        historical_reject_rate_ppm=1800,
        reserved_unit_budget=30000,
    )
    fixtures.activate_project(api, syringe_project["id"])

    vial_batch = fixtures.create_batch(
        api,
        vial_project["id"],
        suite["id"],
        pq_a["id"],
        batch_number="B-001",
        planned_start="2026-09-10T08:00:00Z",
        planned_end="2026-09-10T16:00:00Z",
        target_fill_units=10000,
    )
    syringe_batch = fixtures.create_batch(
        api,
        syringe_project["id"],
        suite["id"],
        pq_a["id"],
        batch_number="B-002",
        planned_start="2026-09-12T08:00:00Z",
        planned_end="2026-09-12T16:00:00Z",
        target_fill_units=10000,
    )
    return {
        "suite_id": suite["id"],
        "vial_project_id": vial_project["id"],
        "syringe_project_id": syringe_project["id"],
        "vial_batch": vial_batch,
        "syringe_batch": syringe_batch,
    }


def test_component_demand_ceilings_each_line_before_summing_them(api):
    """A 10000-container VIAL batch commits 21560 units, never 21000.

    PRD 3.5: "For a `VIAL` batch of 10000 containers, the vial line grosses 10300 units and rounds up to 22 packs of 480, or 10560 units; the stopper line grosses 10500 and rounds up to 11 packs of 1000, or 11000 units; `component_demand_units` is therefore 21560 — not the 21000 that the forbidden sum-then-round order would produce."

    Design: Difficulty/combinatorial_formula/component_demand_per_line_rounding_then_sum
    """
    world = _two_presentations(api)

    vial_batch = world["vial_batch"]
    assert vial_batch["component_demand_units"] == constants.WORKED_COMPONENT_DEMAND_UNITS
    assert (
        vial_batch["component_demand_units"]
        != constants.FORBIDDEN_SUM_THEN_ROUND_DEMAND
    )
    assertions.assert_component_demand(vial_batch, "VIAL")

    syringe_batch = world["syringe_batch"]
    assert syringe_batch["component_demand_units"] == 21500
    assertions.assert_component_demand(syringe_batch, "PRESYRINGE")


def test_component_demand_and_changeover_land_on_both_project_ledgers(api):
    """Each project's committed demand is its own batch's frozen line total.

    PRD 3.5: "A `VIAL` presentation calls for two component lines in this order: `VIAL`, then `STOPPER`."

    Design: Difficulty/combinatorial_formula/component_demand_per_line_rounding_then_sum
    """
    world = _two_presentations(api)

    assert world["vial_batch"]["changeover_minutes_applied"] == constants.INITIAL_SETUP_MINUTES
    assert world["syringe_batch"]["changeover_minutes_applied"] == 240

    vial_project = fixtures.read_project(api, world["vial_project_id"])
    assert vial_project["committed_demand_units"] == 21560
    syringe_project = fixtures.read_project(api, world["syringe_project_id"])
    assert syringe_project["committed_demand_units"] == 21500

    suite = fixtures.read_suite(api, world["suite_id"], PROGRAM_MANAGER)
    assert suite["committed_minutes"] == 1260
