"""Two-variant computations that must not collapse into one another.

Both the releasable-unit pair of PRD 3.8 and the readiness-score pair of PRD 3.9
are deliberately computed from different evidence, so a single stored dataset
has to yield two different integers.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import assertions, constants, fixtures
from test_helpers.test_users import PROGRAM_MANAGER, QA_REVIEWER, QUALIFIED_PERSON

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance: batch_provisional_vs_final_releasable_units_diverge
# ---------------------------------------------------------------------------
def test_unit_accounting_reports_both_releasable_variants_and_their_terms(api):
    """The unit-accounting read exposes both variants and every shared term.

    PRD 3.9: "Addressed at a batch, it returns `batch_order_id`, the `filled_unit_count` both variants start from, the forward-looking `expected_reject_units` derived from the sponsor's historical rate, the `actual_visual_reject_units` actually recorded by visual inspection controls, the `destructive_total_units` both variants subtract, the `quarantined_unit_count` only the final variant subtracts, the stored `provisional_releasable_units` and `final_releasable_units`, and `variant_delta_units`, which is `provisional_releasable_units` minus `final_releasable_units` — positive whenever the sponsor's declared history flattered the batch."

    Design: Difficulty/dual_variant_calc/batch_provisional_vs_final_releasable_units_diverge
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_QP_REVIEW)

    accounting = fixtures.unit_accounting(api, program["batch_id"], QA_REVIEWER)

    assert accounting["batch_order_id"] == program["batch_id"]
    assert accounting["filled_unit_count"] == constants.WORKED_FILLED_UNIT_COUNT
    assert accounting["expected_reject_units"] == constants.WORKED_EXPECTED_REJECT_UNITS
    assert (
        accounting["actual_visual_reject_units"]
        == constants.WORKED_ACTUAL_VISUAL_REJECT_UNITS
    )
    assert accounting["destructive_total_units"] == constants.WORKED_DESTRUCTIVE_TOTAL_UNITS
    assert accounting["quarantined_unit_count"] == 0
    assert (
        accounting["provisional_releasable_units"]
        == constants.WORKED_PROVISIONAL_RELEASABLE_UNITS
    )
    assert accounting["final_releasable_units"] == constants.WORKED_FINAL_RELEASABLE_UNITS
    assert accounting["variant_delta_units"] == constants.WORKED_VARIANT_DELTA_UNITS


def test_provisional_and_final_releasable_units_diverge_on_the_same_batch(api):
    """The stored pair differs, and the production axis is untouched by the close.

    PRD 3.8: "For identical stored data the two figures differ, and `provisional_releasable_units` is never overwritten by the final computation: a batch that filled 8500 containers under a declared historical rate of 2500 parts per million, with 60 destructively sampled units and 166 units rejected at visual inspection and nothing quarantined, carries a provisional figure of 8418 and a final figure of 8274 side by side."

    Design: Difficulty/dual_variant_calc/batch_provisional_vs_final_releasable_units_diverge
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_QP_REVIEW)

    batch = fixtures.read_batch(api, program["batch_id"], QA_REVIEWER)

    assert (
        batch["provisional_releasable_units"]
        == constants.WORKED_PROVISIONAL_RELEASABLE_UNITS
    )
    assert batch["final_releasable_units"] == constants.WORKED_FINAL_RELEASABLE_UNITS
    assert batch["provisional_releasable_units"] != batch["final_releasable_units"]
    assert batch["production_status"] == "FILLED"
    assert batch["quality_status"] == "QP_REVIEW"
    assert (
        assertions.expected_provisional_releasable_units(
            constants.WORKED_FILLED_UNIT_COUNT, 2500, constants.WORKED_DESTRUCTIVE_TOTAL_UNITS
        )
        == batch["provisional_releasable_units"]
    )
    assert (
        assertions.expected_final_releasable_units(
            constants.WORKED_FILLED_UNIT_COUNT,
            constants.WORKED_ACTUAL_VISUAL_REJECT_UNITS,
            constants.WORKED_DESTRUCTIVE_TOTAL_UNITS,
        )
        == batch["final_releasable_units"]
    )


# ---------------------------------------------------------------------------
# Design instance: project_readiness_intake_forecast_vs_gmp_audit_diverge
# ---------------------------------------------------------------------------
def _lapsed_roster_world(api) -> Json:
    """A project at ENGINEERING_RUN whose suite validity and one operator lapsed."""
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api, suite_code="FS-1", grade="B")
    media_fill = fixtures.create_media_fill(
        api, suite["id"], scheduled_run_date="2026-09-02T08:00:00Z"
    )
    fixtures.execute_media_fill(
        api,
        media_fill["id"],
        units_filled=6000,
        participating_operator_names=["OP-A", "OP-B", "OP-C"],
    )
    fixtures.read_media_fill_out(api, media_fill["id"], 0)

    pq_a = fixtures.create_qualification(
        api,
        "OP-A",
        suite["id"],
        qualification_type="ASEPTIC_INTERVENTION",
        expires_on="2027-12-01T00:00:00Z",
        media_fill_id=media_fill["id"],
    )
    fixtures.qualify(api, pq_a["id"])
    pq_b = fixtures.create_qualification(
        api,
        "OP-B",
        suite["id"],
        qualification_type="ASEPTIC_INTERVENTION",
        expires_on="2027-03-15T00:00:00Z",
        media_fill_id=media_fill["id"],
    )
    fixtures.qualify(api, pq_b["id"])
    pq_c = fixtures.create_qualification(
        api,
        "OP-C",
        suite["id"],
        qualification_type="GOWNING",
        expires_on="2027-12-01T00:00:00Z",
    )

    project = fixtures.create_project(
        api,
        suite["id"],
        client_name="Sponsor B",
        molecule_name="MOL-B",
        dosage_form="VIAL",
        target_fill_weight_mg=1000,
        historical_reject_rate_ppm=2500,
        reserved_unit_budget=30000,
    )
    fixtures.advance_tech_transfer(api, project["id"], "GAP_ASSESSMENT", "IN_TRANSFER")
    fixtures.advance_tech_transfer(api, project["id"], "ENGINEERING_RUN", "IN_TRANSFER")
    fixtures.set_clock(api, "2027-04-01T00:00:00Z")
    return {
        "suite_id": suite["id"],
        "media_fill_id": media_fill["id"],
        "project_id": project["id"],
        "pq_a_id": pq_a["id"],
        "pq_b_id": pq_b["id"],
        "pq_c_id": pq_c["id"],
    }


def test_intake_forecast_readiness_is_generous_with_everything_in_flight(api):
    """The commercial variant scores the full 100 on a lapsed, part-pending roster.

    PRD 3.9: "The counted operator population is every qualification of that suite whose `status` is `PENDING`, `QUALIFIED` or `LAPSED`, with `expires_on` ignored; only `REVOKED` records are excluded."

    Design: Difficulty/dual_variant_calc/project_readiness_intake_forecast_vs_gmp_audit_diverge
    """
    world = _lapsed_roster_world(api)

    forecast = fixtures.readiness(
        api, world["project_id"], "INTAKE_FORECAST", PROGRAM_MANAGER
    )

    assert forecast["readiness_score"] == constants.WORKED_INTAKE_FORECAST_SCORE
    assert forecast["tech_points"] == 30
    assert forecast["analytical_points"] == 25
    assert forecast["aseptic_points"] == 25
    assert forecast["operator_points"] == 20
    assert forecast["counted_operator_count"] == 3
    assert forecast["variant"] == "INTAKE_FORECAST"
    assert forecast["client_project_id"] == world["project_id"]


def test_gmp_audit_readiness_credits_only_what_is_effective_at_the_clock(api):
    """The inspection variant scores 47 on the very same stored data.

    PRD 3.9: "The gap between the two views is the point of having both: a project at `ENGINEERING_RUN` with an `IN_TRANSFER` method, a `QUALIFIED` suite whose simulation validity has lapsed, and a roster of one effective operator plus one lapsed and one pending, scores 100 under `INTAKE_FORECAST` and 47 under `GMP_AUDIT`."

    Design: Difficulty/dual_variant_calc/project_readiness_intake_forecast_vs_gmp_audit_diverge
    """
    world = _lapsed_roster_world(api)

    audit = fixtures.readiness(
        api, world["project_id"], "GMP_AUDIT", QUALIFIED_PERSON
    )

    assert audit["readiness_score"] == constants.WORKED_GMP_AUDIT_SCORE
    assert audit["tech_points"] == 15
    assert audit["analytical_points"] == 12
    assert audit["aseptic_points"] == 10
    assert audit["operator_points"] == 10
    assert audit["counted_operator_count"] == 1

    assert fixtures.read_qualification(api, world["pq_a_id"])["status"] == "QUALIFIED"
    assert fixtures.read_qualification(api, world["pq_b_id"])["status"] == "LAPSED"
    assert fixtures.read_qualification(api, world["pq_c_id"])["status"] == "PENDING"
    suite = fixtures.read_suite(api, world["suite_id"])
    assertions.assert_same_instant(
        suite["media_fill_valid_until"],
        constants.MEDIA_FILL_VALID_UNTIL,
        "media_fill_valid_until",
    )
