"""Derived figures at the points where their formulae bite.

Grade A limits collapse alert onto action so the core risk term saturates; the
suite restriction counts action excursions only; the release fee picks its
discount tier once from the pre-discount total; a simulation run is measured
against an inclusive floor and buys exactly 183 days; the lenient readiness
population awards partial operator credit; and the changeover selector falls
back to the initial-setup allowance before reaching for the product-change
buffer.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import MICROBIOLOGY_ANALYST, QUALIFIED_PERSON

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Design instance:
#   em_grade_a_single_colony_is_action_and_the_core_term_saturates_at_one_hundred
# ---------------------------------------------------------------------------
def test_grade_a_colony_is_never_merely_an_alert_and_the_core_term_saturates(api):
    """Zero cfu is clean, one cfu scores 60, and a glove print composes to 125.

    PRD 3.7: "In a grade `A` critical zone the standard is absolute: `alert_limit` and `action_limit` are both 1 for all three sample types, so a single colony anywhere in grade A is an action-level excursion."

    PRD 3.7: "From these, the core term is the ratio multiplied by 20 and then by the grade weight, clamped so that it is never below 0 and never above 100, and then rounded half up to a whole number. The surcharges are added to that rounded core, and `risk_index` is the smaller of 150 and that sum."

    Design: Corner/calculations/em_grade_a_single_colony_is_action_and_the_core_term_saturates_at_one_hundred
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api, suite_code="FS-A", grade="A")

    clean = fixtures.record_em_sample(
        api, suite["id"], sample_type="VIABLE_AIR", cfu_count=0
    )
    assert clean["alert_limit"] == 1
    assert clean["action_limit"] == 1
    assert clean["classification"] == "WITHIN_LIMIT"
    assert clean["risk_index"] == 0
    assert clean["investigation_status"] == "NOT_REQUIRED"

    single_colony = fixtures.record_em_sample(
        api, suite["id"], sample_type="VIABLE_AIR", cfu_count=1
    )
    assert single_colony["classification"] == "ACTION"
    assert single_colony["classification"] != "ALERT"
    assert single_colony["risk_index"] == 60
    assert single_colony["investigation_status"] == "OPEN"
    assertions.assert_em_sample_classification(single_colony, "A")

    glove = fixtures.record_em_sample(
        api, suite["id"], sample_type="PERSONNEL_GLOVE", cfu_count=2
    )
    assert glove["alert_limit"] == 1
    assert glove["action_limit"] == 1
    assert glove["classification"] == "ACTION"
    assert glove["risk_index"] == 125
    assert glove["risk_index"] != 145

    assert fixtures.read_suite(api, suite["id"])["open_action_excursion_count"] == 2


# ---------------------------------------------------------------------------
# Design instance: em_alert_excursion_is_excluded_from_the_open_action_excursion_count
# ---------------------------------------------------------------------------
def test_an_alert_excursion_neither_counts_nor_restricts_the_suite(api):
    """Seven cfu in grade B air scores 28 and opens, yet the suite stays OPEN.

    PRD 2.5: "`open_action_excursion_count` is the number of environmental monitoring samples in this suite whose `classification` is `ACTION` and whose `investigation_status` is either `OPEN` or `INVESTIGATING`; samples classified `ALERT` or `WITHIN_LIMIT` never restrict a suite, and neither does an `ACTION` sample whose investigation has reached `CLOSED`."

    Design: Corner/calculations/em_alert_excursion_is_excluded_from_the_open_action_excursion_count
    """
    world = fixtures.build_qualified_suite(api)
    assert fixtures.read_suite(api, world["suite_id"])["posture"] == constants.POSTURE_OPEN

    sample = validate_success(
        api.create_em_sample(
            factories.em_sample_payload(
                world["suite_id"], sample_type="VIABLE_AIR", cfu_count=7
            ),
            MICROBIOLOGY_ANALYST,
        ),
        201,
    )
    assert sample["alert_limit"] == 5
    assert sample["action_limit"] == 10
    assert sample["classification"] == "ALERT"
    assert sample["risk_index"] == 28
    assert sample["investigation_status"] == "OPEN"
    assertions.assert_em_sample_classification(sample, "B")

    suite = fixtures.read_suite(api, world["suite_id"])
    assert suite["open_action_excursion_count"] == 0
    assert suite["posture"] == constants.POSTURE_OPEN


# ---------------------------------------------------------------------------
# Design instance: qp_release_fee_tier_is_selected_once_from_the_pre_discount_total
# ---------------------------------------------------------------------------
def test_the_discount_tier_is_chosen_from_the_pre_discount_total_only_once(api):
    """8750 units land exactly on the 3 percent boundary and keep the discount.

    PRD 3.8: "**Step four:** the volume discount percentage is chosen from the first matching tier evaluated against the *pre-discount total*: 10 percent for a pre-discount total of at least 2000000 cents, otherwise 6 percent at or above 1000000 cents, otherwise 3 percent at or above 500000 cents, otherwise 0 percent."

    Design: Corner/calculations/qp_release_fee_tier_is_selected_once_from_the_pre_discount_total
    """
    program = fixtures.build_program(
        api,
        stage=fixtures.STAGE_QP_REVIEW,
        filled_unit_count=9000,
        visual_reject_count=190,
    )
    assert program["batch"]["final_releasable_units"] == 8750

    decision = fixtures.qp_release(
        api,
        program["batch_id"],
        QUALIFIED_PERSON,
        decision="RELEASE",
        rationale="Batch record complete, all in-process controls within limits.",
    )
    assert decision["fee_cents"] == 485000
    assert decision["released_unit_count"] == 8750

    batch = fixtures.read_batch(api, program["batch_id"])
    assert batch["release_fee_cents"] == 485000
    assert batch["release_fee_cents"] != 500000
    assert batch["quality_status"] == "RELEASED"
    assertions.assert_release_fee(batch["release_fee_cents"], 8750, "NONE")


# ---------------------------------------------------------------------------
# Design instance:
#   media_fill_minimum_units_boundary_and_one_hundred_eighty_three_day_validity
# ---------------------------------------------------------------------------
def test_the_five_thousand_unit_floor_is_inclusive_and_a_pass_buys_183_days(api):
    """4999 units is refused, 5000 incubates, and the pass expires 2027-03-03.

    PRD 3.2: "The run must be at least 5000 units — exactly 5000 is acceptable, 4999 is not, and an undersized run is refused with `ERR_MEDIA_FILL_UNDERSIZED` (HTTP 422)."

    PRD 3.2: "`media_fill_valid_until` is stamped as the simulation's `read_at` plus 183 days, which is the validity period of an aseptic process simulation (just over six months)."

    Design: Corner/calculations/media_fill_minimum_units_boundary_and_one_hundred_eighty_three_day_validity
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    media_fill = fixtures.create_media_fill(api, suite["id"])

    validate_error(
        api.execute_media_fill(
            media_fill["id"],
            factories.media_fill_execute_payload(
                units_filled=constants.MEDIA_FILL_MIN_UNITS - 1,
                participating_operator_names=["OP-A", "OP-B"],
            ),
            MICROBIOLOGY_ANALYST,
        ),
        ApiErrorId.MEDIA_FILL_UNDERSIZED,
        422,
    )
    assert fixtures.read_media_fill(api, media_fill["id"])["status"] == "SCHEDULED"

    executed = fixtures.execute_media_fill(
        api,
        media_fill["id"],
        units_filled=constants.MEDIA_FILL_MIN_UNITS,
        participating_operator_names=["OP-A", "OP-B"],
    )
    assert executed["status"] == "INCUBATING"
    assert executed["units_filled"] == 5000

    passed = fixtures.read_media_fill_out(api, media_fill["id"], 0)
    assert passed["status"] == "PASSED"

    suite_after = fixtures.read_suite(api, suite["id"])
    assert suite_after["aseptic_qualification_status"] == "QUALIFIED"
    assertions.assert_same_instant(
        suite_after["media_fill_valid_until"],
        constants.MEDIA_FILL_VALID_UNTIL,
        "media_fill_valid_until",
    )
    assert suite_after["qualified_operator_count"] == 0
    assert suite_after["posture"] == constants.POSTURE_RESTRICTED


# ---------------------------------------------------------------------------
# Design instance: readiness_operator_partial_credit_uses_the_lenient_forecast_population
# ---------------------------------------------------------------------------
def test_a_single_pending_gowning_record_earns_ten_forecast_points(api):
    """The lenient population counts the pending record and halves the weight.

    PRD 3.9: "both compute the operator component identically: 20 points when the counted operator population is at least two, and otherwise 20 multiplied by that count divided by two, rounded half up to a whole number."

    PRD 3.9: "The counted operator population is every qualification of that suite whose `status` is `PENDING`, `QUALIFIED` or `LAPSED`, with `expires_on` ignored; only `REVOKED` records are excluded."

    Design: Corner/calculations/readiness_operator_partial_credit_uses_the_lenient_forecast_population
    """
    fixtures.set_clock(api, constants.SCENARIO_CLOCK)
    suite = fixtures.create_suite(api)
    project = fixtures.create_project(api, suite["id"])
    pending = fixtures.create_qualification(
        api, "OP-A", suite["id"], qualification_type="GOWNING"
    )
    assert pending["status"] == "PENDING"

    assessment = fixtures.readiness(api, project["id"], "INTAKE_FORECAST")
    assert assessment["variant"] == "INTAKE_FORECAST"
    assert assessment["client_project_id"] == project["id"]
    assert assessment["tech_points"] == 0
    assert assessment["analytical_points"] == 0
    assert assessment["aseptic_points"] == 0
    assert assessment["counted_operator_count"] == 1
    assert assessment["operator_points"] == 10
    assert assessment["readiness_score"] == 10
    assert assessment["readiness_score"] != 20
    assertions.assert_same_instant(
        assessment["assessed_at"], constants.SCENARIO_CLOCK, "assessed_at"
    )


# ---------------------------------------------------------------------------
# Design instance: changeover_selector_falls_back_then_applies_the_product_change_buffer
# ---------------------------------------------------------------------------
def test_the_first_batch_takes_sixty_minutes_and_the_next_molecule_takes_240(api):
    """Empty-candidate fallback then the product-change buffer, summing to 1020.

    PRD 3.5: "When that candidate set is empty — the new batch is the first thing this suite will run — `changeover_minutes_applied` is the standing initial-setup allowance of 60 minutes, a full hour of room preparation. Otherwise, if the preceding batch's project carries the same `molecule_name` as the new batch's project, `changeover_minutes_applied` is the suite's `changeover_minutes_same_product`; if the molecules differ, it is the suite's `changeover_minutes_product_change`."

    PRD 3.5: "A suite's `committed_minutes` is itself the sum, over every live batch in that suite, of the number of whole minutes between that batch's `planned_start` and `planned_end` plus that batch's `changeover_minutes_applied`"

    Design: Corner/calculations/changeover_selector_falls_back_then_applies_the_product_change_buffer
    """
    program = fixtures.build_program(api, stage=fixtures.STAGE_SCHEDULED)
    assert program["batch"]["changeover_minutes_applied"] == constants.INITIAL_SETUP_MINUTES
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540

    sponsor_b = fixtures.create_project(
        api,
        program["suite_id"],
        client_name="Sponsor B",
        molecule_name="MOL-B",
        target_fill_weight_mg=800,
        historical_reject_rate_ppm=1500,
    )
    fixtures.activate_project(api, sponsor_b["id"])

    second = fixtures.create_batch(
        api,
        sponsor_b["id"],
        program["suite_id"],
        program["qualification_ids"][1],
        batch_number="B-100",
        planned_start="2026-09-11T08:00:00Z",
        planned_end="2026-09-11T12:00:00Z",
        target_fill_units=10000,
    )
    assert second["changeover_minutes_applied"] == 240
    assert second["changeover_minutes_applied"] != 60

    assert fixtures.read_batch(api, program["batch_id"])[
        "changeover_minutes_applied"
    ] == constants.INITIAL_SETUP_MINUTES
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 1020
    assert (
        fixtures.read_project(api, sponsor_b["id"])["committed_demand_units"]
        == constants.WORKED_COMPONENT_DEMAND_UNITS
    )
    assert (
        fixtures.read_project(api, program["project_id"])["committed_demand_units"]
        == constants.WORKED_COMPONENT_DEMAND_UNITS
    )
