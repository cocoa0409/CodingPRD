"""Scaled-score computation: the provisional figure at submission versus the
equated final figure at finalization, and the pass comparison at the cut."""

from test_helpers import (
    TEST_USERS,
    finalize_report,
    get_success_data,
    setup_sitting,
)


def test_provisional_scaled_score_rounds_the_unrounded_ratio_half_up(api):
    """A 55-of-80 submission scales to 68.75 and must be reported as 69.

    PRD: "The `provisional_scaled_score` is 100 multiplied by `raw_correct_count`,
    divided by the form's `scored_item_count`, rounded half up to a whole number;
    the ratio itself is never rounded before the multiplication."

    Design: Difficulty/dual_variant_calc/scaled_score_provisional_vs_final_equated_flips_pass_flag
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=55)
    report = env["score_report"]

    assert report["raw_correct_count"] == 55
    assert report["provisional_scaled_score"] == 69
    assert report["status"] == "PROVISIONAL"
    assert report["voided_item_count"] == 0
    assert report["voided_correct_count"] == 0
    assert report["final_scaled_score"] is None
    assert report["pass_flag"] is None
    assert report["finalized_by_user_id"] is None
    assert report["released_at"] is None


def test_effective_cut_score_is_frozen_from_the_candidates_own_jurisdiction(api):
    """With no override in force the frozen cut is the form's national cut of 70.

    PRD: "when that jurisdiction's `min_passing_score_override` is null the
    effective cut is simply the form's `national_cut_score`, and when an override
    is present the effective cut is the greater of the form's `national_cut_score`
    and that override"

    Design: Difficulty/dual_variant_calc/scaled_score_provisional_vs_final_equated_flips_pass_flag
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=55)

    assert env["exam_form"]["national_cut_score"] == 70
    assert env["jurisdiction"]["min_passing_score_override"] is None
    assert env["score_report"]["effective_cut_score"] == 70
    # 69 is below the frozen cut, so the provisional picture is a failure.
    assert env["score_report"]["provisional_scaled_score"] == 69


def test_equating_voided_items_out_of_both_sides_flips_the_pass_flag(api):
    """Voiding five items the candidate missed lifts 69 to 73 and turns a fail
    into a pass, while the provisional figure survives untouched.

    PRD: "`final_scaled_score` is 100 multiplied by the difference between
    `raw_correct_count` and `voided_correct_count`, divided by the difference
    between the form's `scored_item_count` and `voided_item_count`, rounded half
    up to a whole number; as with the provisional figure, the ratio is never
    rounded before the multiplication."

    Design: Difficulty/dual_variant_calc/scaled_score_provisional_vs_final_equated_flips_pass_flag
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=55)

    final = finalize_report(env, env["score_report"],
                            admin_headers=TEST_USERS["scoring_admin_headers"],
                            voided_item_count=5, voided_correct_count=0)

    # 100 * (55 - 0) / (80 - 5) = 73.33... -> 73
    assert final["final_scaled_score"] == 73
    assert final["pass_flag"] is True
    assert final["voided_item_count"] == 5
    assert final["voided_correct_count"] == 0
    assert final["provisional_scaled_score"] == 69
    assert final["effective_cut_score"] == 70


def test_finalization_closes_the_sitting_and_releases_the_held_interval(api):
    """The finalization cascade closes the sitting, clears its proctoring
    dimension, stamps the operator and releases both reservations.

    PRD: "The report moves `PROVISIONAL → FINAL` with `released_at` set to the
    logical clock and `finalized_by_user_id` set to the finalizing operator's
    `X-User-ID`"

    PRD: "And the sitting's interval is released here rather than at submission:
    the site's `reserved_seat_minutes` and the assigned proctor's
    `reserved_minutes` each fall by the sitting's `allowed_minutes`."

    Design: Difficulty/dual_variant_calc/scaled_score_provisional_vs_final_equated_flips_pass_flag
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=55)
    admin = env["admin_headers"]
    held_site = get_success_data(api.get_testing_site(env["testing_site"]["id"], admin))
    held_proctor = get_success_data(api.get_proctor(env["proctor"]["id"], admin))
    assert held_site["reserved_seat_minutes"] == 120
    assert held_proctor["reserved_minutes"] == 120

    final = finalize_report(env, env["score_report"],
                            admin_headers=TEST_USERS["scoring_admin_headers"],
                            voided_item_count=5, voided_correct_count=0)

    assert final["status"] == "FINAL"
    assert final["finalized_by_user_id"] == "admin-scoring-1"
    assert final["released_at"] is not None

    session = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert session["session_status"] == "CLOSED"
    assert session["proctoring_status"] == "CLEARED"

    assert get_success_data(
        api.get_testing_site(env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 0
    assert get_success_data(
        api.get_proctor(env["proctor"]["id"], admin))["reserved_minutes"] == 0


def test_final_score_exactly_at_the_effective_cut_is_a_pass(api):
    """56 of 80 equates to exactly 70, and 70 against a cut of 70 must pass.

    PRD: "`pass_flag` is then set to true when `final_scaled_score` is greater
    than or equal to the report's frozen `effective_cut_score`, and false
    otherwise — a score exactly equal to the cut is a pass."

    Design: Difficulty/boundary_precision_check/final_score_exactly_at_cut_passes_one_below_fails
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=56)
    assert env["score_report"]["effective_cut_score"] == 70

    final = finalize_report(env, env["score_report"],
                            admin_headers=TEST_USERS["scoring_admin_headers"])

    assert final["final_scaled_score"] == 70
    assert final["pass_flag"] is True
    assert final["voided_item_count"] == 0
    assert final["voided_correct_count"] == 0

    session = get_success_data(api.get_exam_session(env["session"]["id"],
                                                    env["admin_headers"]))
    assert session["session_status"] == "CLOSED"
    assert session["proctoring_status"] == "CLEARED"


def test_final_score_one_point_below_the_cut_is_a_failure(api):
    """55 of 80 equates to 68.75, which rounds half up to 69 and not down to 68,
    and 69 one point under the cut must fail.

    PRD: "an unvoided finalization with both counts at their zero defaults
    reproduces the `provisional_scaled_score` exactly"

    PRD: "`pass_flag` is then set to true when `final_scaled_score` is greater
    than or equal to the report's frozen `effective_cut_score`, and false
    otherwise — a score exactly equal to the cut is a pass."

    Design: Difficulty/boundary_precision_check/final_score_exactly_at_cut_passes_one_below_fails
    """
    env = setup_sitting(stage="SUBMITTED", scored_correct_count=55)
    assert env["score_report"]["effective_cut_score"] == 70

    final = finalize_report(env, env["score_report"],
                            admin_headers=TEST_USERS["scoring_admin_headers"])

    assert final["final_scaled_score"] == 69
    assert final["final_scaled_score"] == final["provisional_scaled_score"]
    assert final["pass_flag"] is False

    session = get_success_data(api.get_exam_session(env["session"]["id"],
                                                    env["admin_headers"]))
    assert session["session_status"] == "CLOSED"
    assert session["proctoring_status"] == "CLEARED"
