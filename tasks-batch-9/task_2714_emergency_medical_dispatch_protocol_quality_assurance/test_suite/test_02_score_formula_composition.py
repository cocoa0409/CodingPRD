"""Multi-step score arithmetic: the pinned rounding order, the penalty tier read
from the pre-penalty composite, and the resuscitation performance index."""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2
from test_helpers.test_users import SUPERVISOR

PROGRAM_THRESHOLDS = {
    "target_compliance_pct": 90.0,
    "watch_floor_pct": 80.0,
    "high_risk_target_pct": 85.0,
    "hours_owed_restriction_threshold": 6.0,
}

# 18/20, 26/30, 2/3 and 5/7: three of the four sections are repeating decimals,
# so rounding each to 2 places before weighting is observable in the composite.
REPEATING_DECIMAL_SHEET = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (2, 3),
    "final_coding": (5, 7),
}


def _repeating_decimal_env(api):
    """One CHEST_PAIN review dispatched 10-C-4 and coded 10-C-2 by the reviewer."""
    return fx.scored_review_env(
        api,
        sections=REPEATING_DECIMAL_SHEET,
        reviewer_determinant_code="10-C-2",
        program_overrides=dict(PROGRAM_THRESHOLDS),
        call_overrides={"call_type": "CHEST_PAIN", "dispatched_determinant_code": "10-C-4"},
        period_overrides={"sampling_mode": "MIXED", "target_sample_count": 1},
    )


def test_section_percentages_are_rounded_to_two_places_before_any_weighting(api):
    """PRD 2.6: "Section percentages are rounded to 2 decimal places first, and the
    composite is then computed from those already-rounded percentages and rounded
    once to 1 decimal place."
    PRD 3.5: "Each is the points earned divided by the points possible, multiplied
    by one hundred, rounded half up to 2 decimal places."

    Design: Difficulty/combinatorial_formula/section_rounding_before_weighting_changes_the_pre_penalty_score
    """
    env = _repeating_decimal_env(api)
    sheet = env["sheet"]

    assert sheet["case_entry_pct"] == approx2(90.00)
    assert sheet["key_questions_pct"] == approx2(86.67), "26/30 = 86.666... rounds half up"
    assert sheet["pre_arrival_pct"] == approx2(66.67), "2/3 = 66.666... rounds half up"
    assert sheet["final_coding_pct"] == approx2(71.43), "5/7 = 71.428... rounds half up"
    # (90.00 + 86.67 + 66.67 + 71.43) / 4 = 78.6925 -> 78.7
    assert sheet["provisional_composite_score"] == approx1(78.7)


def test_pre_penalty_composite_weights_the_already_rounded_percentages(api):
    """PRD 2.6: "The **order** in which rounding is applied is part of the
    specification, not an implementation detail, because rounding early and
    rounding late give different answers."
    PRD 3.7: "The four already-rounded section percentages of the **current** sheet
    — the one whose `sheet_round` equals the review's `current_sheet_round`,
    superseded sheets being excluded entirely — are each multiplied by the
    corresponding weight on the review's pinned protocol version, the four products
    are summed, and the total is rounded half up to 1 decimal place to give
    `pre_penalty_composite_score`."

    Design: Difficulty/combinatorial_formula/section_rounding_before_weighting_changes_the_pre_penalty_score
    """
    env = _repeating_decimal_env(api)

    review = validate_success(
        api.finalize_review(env["review_id"], {"finalization_note": "concur"}, SUPERVISOR), 200
    )

    # 90.00*0.20 + 86.67*0.35 + 66.67*0.30 + 71.43*0.15 = 79.05 -> 79.1.
    # Weighting the unrounded fractions instead would total 79.0.
    assert review["pre_penalty_composite_score"] == approx1(79.1), (
        "rounding each section to 2 places before weighting yields 79.1, not 79.0: got "
        f"{review['pre_penalty_composite_score']}"
    )
    assert review["determinant_accuracy"] == "MINOR_MISCODE"
    assert review["penalty_points"] == approx1(2.0)
    assert review["final_composite_score"] == approx1(77.1)


def test_probation_posture_and_owed_hours_follow_the_rounded_final_score(api):
    """PRD 3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it
    is at or above the programme's `target_compliance_pct`, `WATCH` when it is
    below that but at or above `watch_floor_pct`, and `PROBATION` when it is below
    the watch floor; a dispatcher with no finalized reviews is `UNRATED`."
    PRD 3.8: "For each open plan the shortfall is the plan's `required_hours` less
    its `credited_hours`, floored at 0.00 so that over-delivery on one plan can
    never offset another plan's shortfall; `remediation_hours_owed` is the sum of
    those per-plan shortfalls, rounded half up to 2 decimal places."
    PRD 3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater** than
    the programme's `hours_owed_restriction_threshold`, the privilege is
    `RESTRICTED` — owing exactly the threshold leaves a dispatcher at `FULL`."

    Design: Difficulty/combinatorial_formula/section_rounding_before_weighting_changes_the_pre_penalty_score
    """
    env = _repeating_decimal_env(api)
    fx.finalize(api, env["review_id"], "concur")

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["compliance_pct"] == approx1(77.1)
    assert dispatcher["compliance_posture"] == "PROBATION", "77.1 is below the 80.0 watch floor"
    # A probation posture raises one STANDARD plan owing 4.0 hours.
    assert dispatcher["remediation_hours_owed"] == approx2(4.00)
    assert dispatcher["dispatch_privilege"] == "FULL", "4.00 owed hours does not exceed 6.0"


def _under_triage_env(api, earned=None):
    """A 10-C-4 call the reviewer judges should have been 10-E-1: same ALS resource
    tier, but a HOT response mode against the dispatched COLD one."""
    sections = None
    if earned is not None:
        sections = {
            section: (earned, 25)
            for section in ("case_entry", "key_questions", "pre_arrival", "final_coding")
        }
    return fx.scored_review_env(
        api,
        sections=sections,
        reviewer_determinant_code="10-E-1",
        program_overrides=dict(PROGRAM_THRESHOLDS),
        call_overrides={"call_type": "CHEST_PAIN", "dispatched_determinant_code": "10-C-4"},
        period_overrides={"sampling_mode": "MIXED", "target_sample_count": 1},
    )


def test_under_triage_is_classified_from_the_two_deviation_flags_and_the_ranks(api):
    """PRD 2.10: "The letter maps to a numeric priority rank ordering codes by
    clinical acuity: `O` is rank 1, `A` is rank 2, `B` is rank 3, `C` is rank 4,
    `D` is rank 5, and `E` — the ECHO level, the most acute — is rank 6."
    PRD 3.5: "Two deviation flags then compare the two decodings:
    `response_mode_deviation` is true when the reviewer's response mode differs from
    the call's `response_mode_assigned`, and `resource_deviation` is true when the
    reviewer's resource tier differs from the call's `resource_assigned`."
    PRD 3.5: "Otherwise there is a real deviation, and its direction decides: when
    the reviewer's priority rank is greater than the dispatched rank, the correct
    code was more acute than the one sent and the call was **under-triaged**, so the
    accuracy is `UNDER_TRIAGE`; when the reviewer's rank is lower, the call was sent
    hotter or heavier than it needed and the accuracy is `OVER_TRIAGE`."

    Design: Difficulty/combinatorial_formula/penalty_tier_selected_from_pre_penalty_not_post_penalty_score
    """
    env = _under_triage_env(api)
    sheet = env["sheet"]

    assert sheet["reviewer_priority_rank"] == 6
    assert sheet["reviewer_response_mode"] == "HOT"
    assert sheet["reviewer_resource"] == "ALS"
    assert sheet["response_mode_deviation"] is True, "the reviewer would have run the call HOT"
    assert sheet["resource_deviation"] is False, "both C and E commit an ALS crew"
    assert sheet["determinant_accuracy"] == "UNDER_TRIAGE"
    assert sheet["provisional_composite_score"] == approx1(90.0)


def test_penalty_tier_is_selected_from_the_pre_penalty_composite(api):
    """PRD 2.6: "The determinant penalty tier is chosen from the pre-penalty
    composite and never from the post-penalty result."
    PRD 3.7: "First a base penalty is read from the accuracy class: `ACCURATE`
    carries 0.0, `MINOR_MISCODE` carries 2.0, `OVER_TRIAGE` carries 5.0, and
    `UNDER_TRIAGE` carries 10.0 — under-triage is punished five times as hard as an
    inconsequential miscode, because it is the error that sends a basic-life-support
    crew cold to a dying patient."
    PRD 3.7: "Second, a tier multiplier is selected **from the pre-penalty score,
    never from the post-penalty result**: a pre-penalty score at or above 90.0
    selects the high tier and multiplies the base by 1.5, a pre-penalty score at or
    above 75.0 but below 90.0 selects the mid tier and multiplies by 1.0, and
    anything below 75.0 selects the low tier and multiplies by 0.5."

    Design: Difficulty/combinatorial_formula/penalty_tier_selected_from_pre_penalty_not_post_penalty_score
    """
    env = _under_triage_env(api)

    review = validate_success(
        api.finalize_review(
            env["review_id"], {"finalization_note": "under-triage confirmed"}, SUPERVISOR
        ),
        200,
    )

    assert review["pre_penalty_composite_score"] == approx1(90.0)
    # 90.0 is at the high-tier floor: 10.0 * 1.5 = 15.0. Reading the tier from the
    # post-penalty 75.0 would land in the mid tier and charge only 10.0.
    assert review["penalty_points"] == approx1(15.0), (
        f"expected the high tier multiplier on a 90.0 sheet, got {review['penalty_points']}"
    )
    assert review["final_composite_score"] == approx1(75.0)
    assert review["compliant"] is False


@pytest.mark.parametrize(
    "earned,pre_penalty,penalty,final",
    [
        (20, 80.0, 10.0, 70.0),
        (17, 68.0, 5.0, 63.0),
    ],
)
def test_lower_pre_penalty_composites_select_the_cheaper_tiers(
    api, earned, pre_penalty, penalty, final
):
    """PRD 3.7: "Second, a tier multiplier is selected **from the pre-penalty score,
    never from the post-penalty result**: a pre-penalty score at or above 90.0
    selects the high tier and multiplies the base by 1.5, a pre-penalty score at or
    above 75.0 but below 90.0 selects the mid tier and multiplies by 1.0, and
    anything below 75.0 selects the low tier and multiplies by 0.5."
    PRD 3.7: "`final_composite_score` is the pre-penalty score less the penalty
    points, floored at 0.0 so it can never go negative, rounded half up to 1 decimal
    place."

    Design: Difficulty/combinatorial_formula/penalty_tier_selected_from_pre_penalty_not_post_penalty_score
    """
    env = _under_triage_env(api, earned=earned)

    review = fx.finalize(api, env["review_id"], "under-triage confirmed")

    assert review["determinant_accuracy"] == "UNDER_TRIAGE"
    assert review["pre_penalty_composite_score"] == approx1(pre_penalty)
    assert review["penalty_points"] == approx1(penalty)
    assert review["final_composite_score"] == approx1(final)


def test_dacpr_index_combines_three_subscores_under_the_solo_weight_vector(api):
    """PRD 3.6: "The recognition sub-score decays linearly against a 90-second
    limit: it is one hundred multiplied by the amount by which 90 seconds exceeds
    `recognition_time_sec`, divided by 90, with the shortfall treated as zero once
    the recognition time reaches or passes 90 seconds."
    PRD 3.6: "The instruction sub-score is the sum of two independent observations
    rather than a single flag: 60 points when `dacpr_instructions_delivered` is true
    and nothing when it is false, plus 40 points when `compressions_coached` is true
    and nothing when it is false."
    PRD 3.6: "When the call record's `bystander_cpr_in_progress` is false — the
    dispatcher is working a caller who is doing nothing — recognition carries a
    weight of 40, compression 45, and instruction 15."
    PRD 3.6: "The raw index is each sub-score multiplied by its weight, the three
    products summed, and the total divided by one hundred; `dacpr_index` is that raw
    value rounded half up to 1 decimal place."

    Design: Difficulty/combinatorial_formula/dacpr_index_nested_min_max_with_bystander_weight_branch
    """
    env = fx.high_risk_scored_env(
        api,
        dacpr_overrides={
            "cardiac_arrest_recognized": True,
            "recognition_time_sec": 15,
            "time_to_first_compression_sec": 45,
            "dacpr_instructions_delivered": True,
            "compressions_coached": True,
        },
        call_overrides={"bystander_cpr_in_progress": False},
    )
    record = env["high_risk_review"]

    review = fx.get_review(api, env["review_id"])
    assert review["high_risk"] is True

    assert record["status"] == "DACPR_SCORED"
    assert record["compression_compliant"] is True, "45 seconds is inside the 120-second limit"
    # recognition 100*(90-15)/90 = 83.333..., compression 100*75/90 = 83.333...,
    # instruction 60 + 40 = 100; (40*83.333 + 45*83.333 + 15*100)/100 = 85.833 -> 85.8
    assert record["dacpr_index"] == approx1(85.8), (
        f"expected the 40/45/15 solo weighting to give 85.8, got {record['dacpr_index']}"
    )
    assert record["dacpr_pass"] is True, "85.8 is at or above the 75.0 pass floor"


@pytest.mark.parametrize(
    "bystander_cpr_in_progress,expected_index",
    [
        (False, 63.3),
        (True, 70.8),
    ],
)
def test_bystander_weight_vector_reweights_identical_observations(
    api, bystander_cpr_in_progress, expected_index
):
    """PRD 3.6: "When the call record's `bystander_cpr_in_progress` is false — the
    dispatcher is working a caller who is doing nothing — recognition carries a
    weight of 40, compression 45, and instruction 15."
    PRD 3.6: "When it is true, the dispatcher's recognition speed matters more and
    the time to first compression matters less, so recognition carries 55,
    compression 30, and instruction 15."
    PRD 3.6: "Finally `dacpr_pass` is true when `dacpr_index` is at or above 75.0
    and false otherwise."

    Design: Difficulty/combinatorial_formula/dacpr_index_nested_min_max_with_bystander_weight_branch
    """
    env = fx.high_risk_scored_env(
        api,
        dacpr_overrides={
            "cardiac_arrest_recognized": True,
            "recognition_time_sec": 15,
            "time_to_first_compression_sec": 90,
            "dacpr_instructions_delivered": True,
            "compressions_coached": True,
        },
        call_overrides={"bystander_cpr_in_progress": bystander_cpr_in_progress},
    )
    record = env["high_risk_review"]

    # recognition 83.333..., compression 100*(120-90)/90 = 33.333..., instruction 100.
    # solo: (40*83.333 + 45*33.333 + 15*100)/100 = 63.333 -> 63.3
    # bystander: (55*83.333 + 30*33.333 + 15*100)/100 = 70.833 -> 70.8
    assert record["compression_compliant"] is True
    assert record["dacpr_index"] == approx1(expected_index), (
        f"expected {expected_index} for bystander_cpr_in_progress="
        f"{bystander_cpr_in_progress}, got {record['dacpr_index']}"
    )
    assert record["dacpr_pass"] is False, "neither weighting reaches the 75.0 pass floor"


def test_late_first_compression_zeroes_its_subscore_and_caps_the_rounded_index(api):
    """PRD 3.6: "The sub-score is one hundred multiplied by the remaining time,
    divided by that 90-second span, where the remaining time is the amount by which
    120 seconds exceeds the observed time, treated as zero once the observed time
    reaches or passes 120 seconds and capped at the full 90-second span so that any
    first compression inside 30 seconds earns the whole sub-score."
    PRD 3.6: "One cap then applies after the rounding: when `compression_compliant`
    is false, a late first compression caps the index at 50.0 no matter how strong
    the rest of the performance was, so the stored `dacpr_index` becomes the lower of
    the rounded index and 50.0."

    Design: Difficulty/combinatorial_formula/dacpr_index_nested_min_max_with_bystander_weight_branch
    """
    env = fx.high_risk_scored_env(
        api,
        dacpr_overrides={
            "cardiac_arrest_recognized": True,
            "recognition_time_sec": 0,
            "time_to_first_compression_sec": 130,
            "dacpr_instructions_delivered": True,
            "compressions_coached": True,
        },
        call_overrides={"bystander_cpr_in_progress": False},
    )
    record = env["high_risk_review"]

    assert record["compression_compliant"] is False, "130 seconds is past the 120-second limit"
    # recognition 100, compression 0, instruction 100 -> (4000 + 0 + 1500)/100 = 55.0,
    # then the late-compression cap takes the lower of 55.0 and 50.0.
    assert record["dacpr_index"] == approx1(50.0), (
        f"expected the late-compression cap of 50.0, got {record['dacpr_index']}"
    )
    assert record["dacpr_pass"] is False
