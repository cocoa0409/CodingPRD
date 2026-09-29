"""Multi-input derivations whose intermediate rounding and key ordering are
themselves part of the contract: the confidence formula, the validity tier that
is locked before the staleness penalty lands, and the four-key selector sort.
"""
from test_helpers import (
    activate_rule,
    api_client,
    get_success_data,
    mint_determination,
    new_active_rule,
    new_course,
    new_rule,
    new_student,
    set_clock,
    setup_open_administration,
)
from test_helpers.fixtures import book_attempt, score_attempt
from test_helpers.test_users import make_assessment_staff_headers

# --------------------------------------------------------------------------- #
# base_confidence_round_per_weighted_term_then_sum
# --------------------------------------------------------------------------- #


def _setup_three_component_confidence():
    """A student carrying all three usable measures at once, so every one of the
    three confidence components is non-zero."""
    set_clock("2026-08-15T00:00:00Z")

    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
    )
    new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=10,
        effective_from="2026-08-01T00:00:00Z",
        version_label="V1",
    )
    administration = setup_open_administration(
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-15T00:00:00Z",
        ends_at="2026-08-15T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        race_ethnicity_code="MULTI",
        hs_gpa=3.97,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2026-06-01T00:00:00Z",
        self_guided_pathway="STEM",
    )
    attempt = book_attempt(student["id"], administration["id"])
    scored = score_attempt(attempt["id"], 155)
    return {"course": course, "student": student, "attempt": scored}


def test_weighted_terms_are_rounded_before_they_are_summed():
    """"The intermediate per-measure component scores and the per-measure weighted
    terms that feed them are each rounded to exactly 2 decimal places *before* they
    are summed, and the sum is then rounded to 1 decimal place. Summing unrounded
    weighted terms and rounding once at the end is a different algorithm and is not
    what this system specifies."

    Design: Difficulty/combinatorial_formula/base_confidence_round_per_weighted_term_then_sum
    """
    setup = _setup_three_component_confidence()
    assert setup["attempt"]["scaled_score"] == 969

    determination = mint_determination(setup["student"]["id"], subject_area="MATH")

    assert float(determination["base_confidence_score"]) == 92.6
    assert float(determination["base_confidence_score"]) != 92.5


def test_all_three_components_are_evaluated_whatever_measure_placed_the_student():
    """"Note also that all three components are always evaluated: a student placed
    by test score still earns transcript credit if they have a usable GPA, because
    confidence measures how much evidence stands behind the placement, not how the
    placement was reached."  Here the transcript rule wins the placement, yet the
    scaled score and the self-guided declaration both still feed confidence.

    Design: Difficulty/combinatorial_formula/base_confidence_round_per_weighted_term_then_sum
    """
    setup = _setup_three_component_confidence()

    determination = mint_determination(setup["student"]["id"], subject_area="MATH")

    assert determination["measure_type_used"] == "TRANSCRIPT_GPA"
    assert determination["source_attempt_id"] is None
    assert float(determination["staleness_penalty"]) == 0.0
    assert float(determination["confidence_score"]) == 92.6
    assert determination["validity_days"] == 730
    assert determination["expires_at"] == "2028-08-14T00:00:00Z"
    assert determination["evidence_state"] == "VERIFIED"


# --------------------------------------------------------------------------- #
# validity_tier_locked_to_base_score_not_recomputed_after_staleness
# --------------------------------------------------------------------------- #


def _setup_locked_validity_tier():
    """A student whose base confidence lands exactly on the top tier boundary and
    whose transcript is old enough to attract the staleness penalty."""
    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
    )
    new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    administration = setup_open_administration(
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        race_ethnicity_code="NHPI",
        hs_gpa=3.28,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2022-05-21T00:00:00Z",
        self_guided_pathway="BSTEM",
    )
    attempt = book_attempt(student["id"], administration["id"])
    scored = score_attempt(attempt["id"], 160)
    return {"course": course, "student": student, "attempt": scored}


def test_validity_tier_is_taken_from_the_base_score_at_its_inclusive_boundary():
    """"**Validity** is tiered off `base_confidence_score` -- the figure *before*
    any staleness penalty. A base of at least 85.0 earns `validity_days` of 730; a
    base of at least 70.0 but below 85.0 earns 365; anything below 70.0 earns 180.
    `expires_at` is `determined_at` advanced by that many days."

    Design: Difficulty/combinatorial_formula/validity_tier_locked_to_base_score_not_recomputed_after_staleness
    """
    setup = _setup_locked_validity_tier()
    assert setup["attempt"]["scaled_score"] == 1000

    determination = mint_determination(setup["student"]["id"], subject_area="MATH")

    assert float(determination["base_confidence_score"]) == 85.0
    assert determination["validity_days"] == 730
    assert determination["expires_at"] == "2028-07-31T00:00:00Z"


def test_staleness_penalty_drags_confidence_below_the_tier_that_produced_it():
    """"Both `validity_days` and `expires_at` are fixed at this moment and are
    never recomputed afterwards, even though the penalty applied next may drag the
    stored `confidence_score` below the tier boundary that produced them."

    Design: Difficulty/combinatorial_formula/validity_tier_locked_to_base_score_not_recomputed_after_staleness
    """
    setup = _setup_locked_validity_tier()

    determination = mint_determination(setup["student"]["id"], subject_area="MATH")

    assert float(determination["staleness_penalty"]) == 16.0
    assert float(determination["confidence_score"]) == 69.0
    assert determination["validity_days"] == 730
    assert determination["expires_at"] == "2028-07-31T00:00:00Z"
    assert determination["evidence_state"] == "UNVERIFIED"


# --------------------------------------------------------------------------- #
# selector_ranking_level_rank_then_measure_precedence_then_priority
# --------------------------------------------------------------------------- #


def _setup_four_key_ranking():
    """Four rules laid out so that each ranking key in turn is the one that
    decides: two courses tie on `level_rank`, two rules tie on measure precedence,
    and only then does `priority_rank` separate them."""
    set_clock("2026-08-05T00:00:00Z")

    course_100 = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
    )
    course_stat = new_course(
        course_code="STAT-100",
        title="Introductory Statistics",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
    )
    course_050 = new_course(
        course_code="MATH-050",
        title="Elementary Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )

    rule_a = new_active_rule(
        course_100["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=600,
        priority_rank=1,
        effective_from="2026-08-01T00:00:00Z",
        version_label="V1",
    )
    rule_b = new_active_rule(
        course_stat["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=99,
        effective_from="2026-08-01T00:00:00Z",
        version_label="V1",
    )
    rule_c = new_active_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=1,
        effective_from="2026-08-01T00:00:00Z",
        version_label="V1",
    )
    rule_d = new_rule(
        course_100["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=50,
        effective_from="2026-08-01T00:00:00Z",
        version_label="V2",
    )

    administration = setup_open_administration(
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-05T00:00:00Z",
        ends_at="2026-08-05T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        race_ethnicity_code="AIAN",
        hs_gpa=3.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2026-05-01T00:00:00Z",
    )
    attempt = book_attempt(student["id"], administration["id"])
    scored = score_attempt(attempt["id"], 100)
    return {
        "course_100": course_100,
        "course_stat": course_stat,
        "course_050": course_050,
        "rule_a": rule_a,
        "rule_b": rule_b,
        "rule_c": rule_c,
        "rule_d": rule_d,
        "student": student,
        "attempt": scored,
    }


def test_measure_precedence_breaks_the_level_rank_tie_before_priority_is_read():
    """"The first key is the `level_rank` of the rule's `target_course_id`, in
    *descending* order, so the most advanced course wins. The second key breaks
    ties among equally advanced courses by measure precedence, in ascending order,
    where transcript GPA precedes test score and test score precedes self-guided
    declaration."  The transcript rule wins over the test rule at the same
    `level_rank` even though the test rule carries the far better
    `priority_rank`.

    Design: Difficulty/combinatorial_formula/selector_ranking_level_rank_then_measure_precedence_then_priority
    """
    setup = _setup_four_key_ranking()
    assert setup["attempt"]["scaled_score"] == 625

    determination = mint_determination(setup["student"]["id"], subject_area="MATH")

    assert determination["applied_rule_id"] == setup["rule_b"]["id"]
    assert determination["measure_type_used"] == "TRANSCRIPT_GPA"
    assert determination["placed_course_id"] == setup["course_stat"]["id"]
    assert determination["source_attempt_id"] is None


def test_priority_rank_decides_once_level_rank_and_measure_precedence_both_tie():
    """"The third key is `priority_rank`, ascending, so a smaller number wins."
    Activating a second transcript rule at the same `level_rank` and a lower
    `priority_rank` moves the placement onto it, while rules targeting a different
    course are untouched.

    Design: Difficulty/combinatorial_formula/selector_ranking_level_rank_then_measure_precedence_then_priority
    """
    setup = _setup_four_key_ranking()
    first = mint_determination(setup["student"]["id"], subject_area="MATH")

    activate_rule(setup["rule_d"]["id"])
    second = mint_determination(setup["student"]["id"], subject_area="MATH")

    assert second["applied_rule_id"] == setup["rule_d"]["id"]
    assert second["placed_course_id"] == setup["course_100"]["id"]

    staff = make_assessment_staff_headers()
    superseded = get_success_data(
        api_client.get_placement_determination(first["id"], staff)
    )
    assert superseded["placement_state"] == "SUPERSEDED"
    assert superseded["superseded_by_id"] == second["id"]

    for rule_key in ("rule_b", "rule_c"):
        rule = get_success_data(
            api_client.get_placement_rule(setup[rule_key]["id"], staff)
        )
        assert rule["status"] == "ACTIVE"
