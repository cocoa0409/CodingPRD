"""Progress metrics, goal progress, lean-mass, and the eligibility composite score.

Queue A: dual_variant_calc (scale vs lean-adjusted divergence),
         combinatorial_formula (eligibility composite, 3 inputs).
Queue B: calculations (goal 50%, uncounted excluded, MEAL below threshold),
         entities (lean_mass computed).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]


def test_scale_and_lean_progress_diverge_on_same_member(api):
    """PRD §3.6: "let the weight lost be the baseline weight minus the latest
    weight, and let the nominal target band be the baseline weight multiplied by
    0.10 (a ten-percent-of-body-weight goal band). The metric is the weight lost
    divided by that target band, multiplied by 100, clamped to the range 0 through
    100, and rounded to two decimal places using round-half-up."
    PRD §3.6: "The fat lost is computed as the baseline fat mass (baseline weight
    minus baseline lean mass) minus the latest fat mass (latest weight minus
    latest lean mass). The denominator is again the baseline weight multiplied by
    0.10."

    Design: Difficulty/dual_variant_calc/progress_scale_vs_lean_adjusted_diverge_on_member
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    member_id = ctx["member"]["id"]
    enr_id = ctx["enrollment"]["id"]
    fixtures.record_counted_weighin(enr_id, 90, body_fat_pct=25)
    member = validate_success(api.get_member(member_id, ADMIN), 200)
    assert member["scale_progress_pct"] == 52.63, (
        f"scale_progress_pct must be 52.63, got {member['scale_progress_pct']}"
    )
    assert member["lean_adjusted_progress_pct"] == 63.16, (
        f"lean_adjusted_progress_pct must be 63.16, got {member['lean_adjusted_progress_pct']}"
    )
    assert member["scale_progress_pct"] != member["lean_adjusted_progress_pct"], (
        "the two metrics must diverge for the same member"
    )


def test_scale_progress_set_lean_zero_without_body_fat(api):
    """PRD §3.6: "The first metric, **scale-weight progress**
    (`scale_progress_pct`), credits raw scale-weight loss and ignores body
    composition entirely."
    PRD §3.6: "The second metric, **lean-mass-adjusted progress**
    (`lean_adjusted_progress_pct`) ... It is zero whenever the member's baseline
    weight or latest lean mass is null."

    Design: Difficulty/dual_variant_calc/progress_scale_vs_lean_adjusted_diverge_on_member
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    member_id = ctx["member"]["id"]
    enr_id = ctx["enrollment"]["id"]
    # Counted weigh-in WITHOUT body_fat_pct -> latest_lean_mass null -> lean metric 0.
    fixtures.record_counted_weighin(enr_id, 90)
    member = validate_success(api.get_member(member_id, ADMIN), 200)
    assert member["scale_progress_pct"] == 52.63, (
        f"scale_progress_pct must be 52.63, got {member['scale_progress_pct']}"
    )
    assert member["lean_adjusted_progress_pct"] == 0, (
        f"lean metric must be 0 when latest lean mass is null, got {member['lean_adjusted_progress_pct']}"
    )


def test_lean_mass_computed_on_weighin(api):
    """PRD §3.6: "computes `lean_mass_kg` as the weight multiplied by one minus the
    body-fat fraction (the percent divided by 100), rounded to two decimal places
    using round-half-up."

    Design: Corner/entities/weighin_lean_mass_computed_correctly
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    member_id = ctx["member"]["id"]
    enr_id = ctx["enrollment"]["id"]
    version = fixtures.get_enrollment_version(enr_id)
    payload = f.create_weighin_payload(enr_id, 90, version, body_fat_pct=25)
    wi = validate_success(api.create_weighin(payload, fixtures.make_member_headers(member_id)), 201)
    assert wi["lean_mass_kg"] == 67.5, f"lean_mass(90,25%) must be 67.5, got {wi['lean_mass_kg']}"


def test_eligibility_composite_score_three_inputs(api):
    """PRD §3.9: "subtract a base of 25.0 from the BMI, take whichever is larger of
    that difference and zero, multiply by a per-point weight of 4, and cap the
    result at 40."
    PRD §3.9: "The tier contribution is 20 when the enrollment's plan tier is
    `RX`, 10 when it is `COACHING`, and 5 otherwise (that is, for `MEAL`). The
    composite score is the sum of these three contributions."

    Design: Difficulty/combinatorial_formula/eligibility_composite_score_nonlinear_three_inputs
    """
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000},
        intake_weight_kg=95,
        comorbidity_count=0,
    )
    det = validate_success(
        api.create_eligibility(
            f.create_eligibility_payload(ctx["member"]["id"], ctx["enrollment"]["id"]), CLINICIAN
        ),
        201,
    )
    assert det["composite_score"] == 51.6, (
        f"composite_score (BMI 32.9, comorbid 0, RX) must be 51.6, got {det['composite_score']}"
    )


def test_eligibility_composite_score_coaching_tier_branch(api):
    """PRD §3.9: "The tier contribution is 20 when the enrollment's plan tier is
    `RX`, 10 when it is `COACHING`, and 5 otherwise (that is, for `MEAL`). The
    composite score is the sum of these three contributions."
    PRD §3.9: "subtract a base of 25.0 from the BMI, take whichever is larger of
    that difference and zero, multiply by a per-point weight of 4, and cap the
    result at 40."

    Design: Difficulty/combinatorial_formula/eligibility_composite_score_nonlinear_three_inputs
    """
    # BMI 32.9 -> bmi_pts 31.6; comorbid 0 -> 0; COACHING tier -> 10; total 41.6.
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "COACHING", "monthly_fee_cents": 6000},
        intake_weight_kg=95,
        comorbidity_count=0,
    )
    det = validate_success(
        api.create_eligibility(
            f.create_eligibility_payload(ctx["member"]["id"], ctx["enrollment"]["id"]), CLINICIAN
        ),
        201,
    )
    assert det["composite_score"] == 41.6, (
        f"composite_score (BMI 32.9, comorbid 0, COACHING) must be 41.6, got {det['composite_score']}"
    )


def test_eligibility_score_meal_low_bmi_below_threshold(api):
    """PRD §3.9: "The composite score is the sum of these three contributions."
    PRD §3.9: "Approval requires the composite score to be at least the eligibility
    threshold of 35 (else `ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD`)."

    Design: Corner/calculations/eligibility_score_meal_low_bmi_below_threshold
    """
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "MEAL", "monthly_fee_cents": 4000},
        intake_weight_kg=78,
        comorbidity_count=0,
    )
    det = validate_success(
        api.create_eligibility(
            f.create_eligibility_payload(ctx["member"]["id"], ctx["enrollment"]["id"]), CLINICIAN
        ),
        201,
    )
    assert det["composite_score"] == 13.0, (
        f"composite_score (BMI 27.0, comorbid 0, MEAL) must be 13.0, got {det['composite_score']}"
    )
    resp = api.approve_eligibility(det["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_SCORE_BELOW_THRESHOLD.value, 409)


def test_goal_progress_50_percent(api):
    """PRD §3.6: "let the span be the baseline weight minus the target weight
    (always positive by the target validation) and the weight lost be the baseline
    weight minus the member's latest weight, and the progress is the weight lost
    divided by the span, multiplied by 100, clamped to 0 through 100, and rounded
    to two decimal places using round-half-up."

    Design: Corner/calculations/goal_progress_50_percent_correct
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    enr_id = ctx["enrollment"]["id"]
    goal = fixtures.create_goal(enr_id, "PRIMARY", 85)
    fixtures.record_counted_weighin(enr_id, 90)
    fetched = validate_success(api.get_goal(goal["id"], ADMIN), 200)
    assert fetched["progress_pct"] == 50.0, (
        f"goal progress (baseline 95, target 85, latest 90) must be 50.0, got {fetched['progress_pct']}"
    )
    assert fetched["status"] == "OPEN", "50% progress must keep the goal OPEN"


def test_uncounted_weighin_excluded_from_progress(api):
    """PRD §3.6: "When `counts` is false the weigh-in is retained for the audit
    trail but excluded from every baseline, latest-weight, progress, and
    graduation computation."

    Design: Corner/calculations/uncounted_weighin_excluded_from_progress
    """
    ctx = fixtures.create_active_enrollment(intake_weight_kg=95)
    enr_id = ctx["enrollment"]["id"]
    member_id = ctx["member"]["id"]
    fixtures.record_counted_weighin(enr_id, 90)  # counted
    # uncounted weigh-in at 80 must not move latest/progress
    version = fixtures.get_enrollment_version(enr_id)
    payload = f.create_weighin_payload(enr_id, 80, version, counts=False)
    validate_success(api.create_weighin(payload, TEST_USERS["coach_headers"]), 201)
    member = validate_success(api.get_member(member_id, ADMIN), 200)
    assert member["latest_weight_kg"] == 90, (
        f"latest_weight_kg must stay at the counted 90, got {member['latest_weight_kg']}"
    )
    assert member["scale_progress_pct"] == 52.63, (
        f"scale_progress_pct must reflect only counted weigh-in (52.63), got {member['scale_progress_pct']}"
    )
