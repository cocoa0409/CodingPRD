"""Two computation variants writing the same field must disagree on purpose."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_area,
    assert_index,
    assert_money,
    assert_segment_condition,
)
from test_helpers.constants import (
    AREA_MAPLE,
    DEFAULT_CLOCK,
    FUNDING_LARGE,
    GRAND_CANDIDATE_COST,
    MAPLE_CANDIDATE_COST,
    OAK_TOTAL,
    OBS_MILL,
    OBS_MILL_DEDUCT,
    OBS_MILL_INDEX,
    SEG_MAPLE,
    SOURCE_MODEL_PROJECTED,
    SOURCE_SURVEY_MEASURED,
)
from test_helpers.factories import (
    acceptance_decision_payload,
    acceptance_test_payload,
    award_payload,
    notice_payload,
    schedule_notice_payload,
)
from test_helpers.test_users import (
    ENGINEER,
    INSPECTOR_DECIDER_2,
    INSPECTOR_WITNESS_2,
    OFFICER_AWARDER,
)


def test_segment_creation_publishes_the_model_projected_variant(api):
    """Creation seeds condition_index from the deterioration model, not from distress.

    PRD: "The `MODEL_PROJECTED` variant ignores every distress measurement and
    derives the index from the deterioration model at creation, or from the
    treatment's restorative gain at acceptance."

    Maple St is a LOCAL block 1000.00 ft by 30.00 ft with a baseline of 92.0 last
    treated on 2016-08-01, so at the 2026-08-01 clock it is exactly ten whole
    years old, two of them past the eight-year knee: 92.0 - 1.4*10 - 1.0*2 = 76.0.

    Design: Difficulty/dual_variant_calc/segment_pci_survey_measured_vs_model_projected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    segment = fixtures.create_segment(api, SEG_MAPLE)

    assert_area(segment["area_sy"], AREA_MAPLE)
    assert segment["decay_coefficient"] == 1.4
    assert segment["decay_knee_coefficient"] == 1.0
    assert_segment_condition(segment, 76.0, SOURCE_MODEL_PROJECTED, "GOOD")
    assert segment["baseline_condition_index"] == 92.0


def test_seal_swaps_in_the_survey_measured_variant_and_flips_the_band(api):
    """Sealing overwrites the same field with pure distress-deduct arithmetic.

    PRD: "The `SURVEY_MEASURED` variant sets `condition_index` to the accepted
    observation's `measured_condition_index`, which is pure distress-deduct
    arithmetic: it ignores `baseline_condition_index` and pavement age entirely."

    The same Maple St row that published 76.0 / GOOD from the model publishes
    69.1 / FAIR from the measurement — a 6.9-point divergence and a band flip.

    Design: Difficulty/dual_variant_calc/segment_pci_survey_measured_vs_model_projected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    segment = fixtures.create_segment(api, SEG_MAPLE)
    survey = fixtures.open_survey(api)
    observation = fixtures.file_observation(api, survey["id"], segment["id"], OBS_MILL)
    assert observation["deduct_total"] == OBS_MILL_DEDUCT
    assert_index(observation["measured_condition_index"], OBS_MILL_INDEX)
    fixtures.accept_observation(api, observation["id"])

    sealed = validate_success(api.seal_survey(survey["id"], ENGINEER))
    republished = get_success_data(api.get_segment(segment["id"], ENGINEER))

    assert_index(sealed["network_condition_index"], 69.1)
    assert_segment_condition(republished, 69.1, SOURCE_SURVEY_MEASURED, "FAIR")
    assert round(76.0 - republished["condition_index"], 1) == 6.9
    assert republished["baseline_condition_index"] == 92.0


def test_run_publishes_the_funded_arm_of_the_projection(api):
    """The funded arm restarts every funded segment on its post-treatment curve.

    PRD: "For a segment that *is* funded, the treatment resets the clock, so the
    projection starts from the post-treatment level — the smaller of 100.0 and
    the sum of the candidate's `selection_condition_index` and its
    `treatment_pci_gain` — and subtracts only the pre-knee rate multiplied by the
    horizon, plus the knee rate multiplied by the amount by which the horizon
    alone exceeds 8 years, then clamps into 0.0 through 100.0 and rounds to one
    decimal place."

    Design: Difficulty/dual_variant_calc/scenario_projection_funded_arm_vs_do_nothing_arm
    """
    ctx = fixtures.sealed_survey(api, fixtures.MAPLE_AND_GRAND)
    assert_index(ctx["survey"]["network_condition_index"], 37.8)

    candidates = fixtures.generate_candidates(api, ctx["survey"]["id"])
    assert_money(candidates[0]["estimated_cost_cents"], GRAND_CANDIDATE_COST)
    assert_money(candidates[1]["estimated_cost_cents"], MAPLE_CANDIDATE_COST)

    scenario = fixtures.create_scenario(
        api, ctx["survey"]["id"], funding_cents=FUNDING_LARGE, horizon_years=10
    )
    run = validate_success(api.run_scenario(scenario["id"], OFFICER_AWARDER))

    assert run["allocation_count"] == 2
    assert_money(run["funded_cost_cents"], 247843264)
    assert_money(run["backlog_cents"], 0)
    assert_index(run["projected_network_pci"], 76.6)


def test_run_publishes_the_do_nothing_arm_over_the_same_segments(api):
    """The comparison arm decays every segment as if nothing had been funded.

    PRD: "`do_nothing_network_pci` is the same weighted mean computed with every
    segment on the unfunded curve regardless of allocation; it is the comparison
    arm that shows what the network does at zero funding."

    One run over Maple St and Grand Blvd publishes 76.6 on the funded arm and
    9.0 on the do-nothing arm: a 67.6-point spread from one set of inputs.

    Design: Difficulty/dual_variant_calc/scenario_projection_funded_arm_vs_do_nothing_arm
    """
    ctx = fixtures.sealed_survey(api, fixtures.MAPLE_AND_GRAND)
    fixtures.generate_candidates(api, ctx["survey"]["id"])
    scenario = fixtures.create_scenario(
        api, ctx["survey"]["id"], funding_cents=FUNDING_LARGE, horizon_years=10
    )

    run = validate_success(api.run_scenario(scenario["id"], OFFICER_AWARDER))

    assert_index(run["do_nothing_network_pci"], 9.0)
    assert_index(run["projected_network_pci"], 76.6)
    assert round(run["projected_network_pci"] - run["do_nothing_network_pci"], 1) == 67.6
    assert_money(run["funding_cents"], FUNDING_LARGE)


def _two_project_contractor(api):
    """Accepted Maple St project plus an in-flight Oak St project under test."""
    ctx = fixtures.adopted_program(api, fixtures.MAPLE_AND_OAK)
    ctx = fixtures.accepted_project(
        api,
        ctx,
        completion_clock="2026-09-30T00:00:00Z",
        acceptance_clock="2026-09-30T00:00:00Z",
    )
    assert ctx["project"]["days_late"] == 0

    project_b = fixtures.create_project(
        api,
        ctx["scenario"]["id"],
        "Z1",
        project_name="Oak St crack seal",
        planned_start_date="2026-10-01T00:00:00Z",
        planned_end_date="2026-10-31T00:00:00Z",
    )
    oak = fixtures.segment_for(ctx, "Oak St")
    line_b = fixtures.add_line(
        api,
        project_b["id"],
        oak["id"],
        fixtures.candidate_for(ctx, "Oak St")["id"],
        "2026-10-01T00:00:00Z",
        "2026-10-31T00:00:00Z",
    )
    fixtures.advance(api, project_b["id"], "START_COORDINATION")
    for row in fixtures.list_coordinations(api, project_b["id"]):
        fixtures.respond_coordination(api, row["id"], "CLEAR")
    project_b = fixtures.advance(api, project_b["id"], "BID_READY")
    assert_money(project_b["project_total_estimate_cents"], OAK_TOTAL)
    validate_success(
        api.award_project(
            project_b["id"],
            award_payload(ctx["contractor"]["id"], OAK_TOTAL),
            OFFICER_AWARDER,
        )
    )
    validate_success(
        api.notice(
            line_b["id"],
            schedule_notice_payload("2026-10-05T00:00:00Z", "2026-10-31T00:00:00Z"),
            ENGINEER,
        )
    )
    validate_success(api.notice(line_b["id"], notice_payload("DELIVER"), ENGINEER))
    fixtures.advance(api, project_b["id"], "START_CONSTRUCTION")

    failing = validate_success(
        api.create_acceptance_test(
            acceptance_test_payload(
                line_b["id"],
                INSPECTOR_WITNESS_2["X-User-ID"],
                core_density_pct=91.9,
                iri_in_per_mi=60.0,
                thickness_in=2.0,
            ),
            INSPECTOR_WITNESS_2,
        ),
        201,
    )
    return ctx, project_b, failing


def test_interim_score_counts_the_failed_test_on_the_in_flight_project(api):
    """The interim variant sees every project's tests, whatever its delivery state.

    PRD: "It counts test decisions and remediation events across *all* of the
    contractor's projects regardless of `delivery_status`, but counts schedule
    lateness only for projects that have reached `SUBSTANTIALLY_COMPLETE` or
    `ACCEPTED` — an in-flight project contributes zero late days even when the
    logical clock has already passed its `planned_end_date`."

    Design: Difficulty/dual_variant_calc/contractor_interim_vs_final_performance_score_diverge
    """
    ctx, _project_b, failing = _two_project_contractor(api)
    assert failing["computed_pay_factor"] == 0.0
    assert failing["computed_outcome"] == "FAIL"

    validate_success(
        api.decide_acceptance_test(
            failing["id"], acceptance_decision_payload("FAIL", "test decision recorded"), INSPECTOR_DECIDER_2
        )
    )
    card = validate_success(
        api.get_contractor_scorecard(ctx["contractor"]["id"], ENGINEER)
    )

    assert card["passed_test_count"] == 1
    assert card["failed_test_count"] == 1
    assert card["remediation_event_count"] == 1
    assert card["days_late_total"] == 0
    assert card["accepted_project_count"] == 1
    assert card["interim_quality_component"] == 50.00
    assert card["interim_schedule_component"] == 100.00
    assert card["interim_remediation_component"] == 92.00
    assert card["interim_performance_score"] == 75.5


def test_final_score_ignores_the_failed_test_on_the_in_flight_project(api):
    """The final variant is restricted to accepted projects, so it stays at 100.0.

    PRD: "The **final** variant, stored as `final_performance_score`, is written
    on project acceptance and is restricted to projects whose `delivery_status`
    is `ACCEPTED`: only tests on lines of accepted projects feed its quality
    component, only remediation events on accepted projects feed its remediation
    component, and `days_late_total` — which sums `days_late` over accepted
    projects only — feeds its schedule component."

    Standing follows the interim variant alone, so the same row reads
    final 100.0 / interim 75.5 / WATCH.

    Design: Difficulty/dual_variant_calc/contractor_interim_vs_final_performance_score_diverge
    """
    ctx, _project_b, failing = _two_project_contractor(api)
    validate_success(
        api.decide_acceptance_test(
            failing["id"], acceptance_decision_payload("FAIL", "test decision recorded"), INSPECTOR_DECIDER_2
        )
    )

    card = validate_success(
        api.get_contractor_scorecard(ctx["contractor"]["id"], ENGINEER)
    )

    assert card["final_quality_component"] == 100.00
    assert card["final_schedule_component"] == 100.00
    assert card["final_remediation_component"] == 100.00
    assert card["final_performance_score"] == 100.0
    assert card["standing"] == "WATCH"
    assert round(card["final_performance_score"] - card["interim_performance_score"], 1) == 24.5
