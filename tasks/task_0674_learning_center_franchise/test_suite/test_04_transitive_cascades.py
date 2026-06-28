"""Transitive cascades: mastering the final level bubbles the enrollment to
COMPLETED (depth-3 from grade); placing a second sibling recomputes sibling_count and
re-derives the first sibling's monthly_rate (depth-2 from place).

Queue A — Difficulty/transitive_cascade.
"""
from test_helpers import (
    validate_success,
    setup_active_enrollment_with_worksheet, setup_operating_center_with_subject,
    create_family, create_student, create_enrollment, create_and_place_enrollment,
    place_enrollment, make_center_director_headers, make_instructor_headers,
)
from test_helpers import api_client as api

DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


# ===========================================================================
# worksheet_mastery_advances_level_then_completes_enrollment_depth3
# ===========================================================================
def test_mastering_only_level_set_marks_worksheet_mastered():
    """PRD §3.4: "if the `score` is greater than or equal to the targeted level's
    `mastery_score_threshold`, the set advances from `GRADED` to `MASTERED`"
    PRD §3.4: "recompute `mastered_sets_in_level` as the count of distinct `set_number`
    values among the enrollment's worksheets whose status is `MASTERED` and whose
    `level_id` equals the enrollment's `current_level_id`."

    A single-level subject with worksheets_to_master=1: grading set #1 at 95 -> MASTERED,
    mastered_sets_in_level 1.

    Design: Difficulty/transitive_cascade/worksheet_mastery_advances_level_then_completes_enrollment_depth3
    """
    *_rest, enrollment, ws = setup_active_enrollment_with_worksheet(
        worksheets_to_master=1, mastery_score_threshold=80)
    graded = validate_success(api.grade_worksheet(ws["id"], {"score": 95}, INSTRUCTOR))
    assert graded["status"] == "MASTERED"
    fresh = validate_success(api.get_enrollment(enrollment["id"], DIRECTOR))
    assert fresh["mastered_sets_in_level"] == 1


def test_mastering_top_level_target_completes_enrollment():
    """PRD §3.4: "If no higher level exists and the mastery target has been met, the
    enrollment moves from `ACTIVE` to the terminal `COMPLETED`."
    PRD §3.4: "only if `mastered_sets_in_level` is greater than or equal to the current
    level's `worksheets_to_master`, look for the next level"

    On the single top level (worksheets_to_master=1), mastering set #1 meets the target
    with no higher level, bubbling the enrollment ACTIVE -> COMPLETED.

    Design: Difficulty/transitive_cascade/worksheet_mastery_advances_level_then_completes_enrollment_depth3
    """
    *_rest, enrollment, ws = setup_active_enrollment_with_worksheet(
        worksheets_to_master=1, mastery_score_threshold=80)
    validate_success(api.grade_worksheet(ws["id"], {"score": 95}, INSTRUCTOR))
    fresh = validate_success(api.get_enrollment(enrollment["id"], DIRECTOR))
    assert fresh["status"] == "COMPLETED", \
        f"top-level mastery target met -> COMPLETED, got {fresh['status']}"


# ===========================================================================
# enrollment_place_recomputes_sibling_count_then_monthly_rate_depth2
# ===========================================================================
def _family_first_placed_second_pending():
    """OPERATING center + subject + level + family with two students; student-1's
    enrollment placed ACTIVE; student-2's enrollment created PLACEMENT_PENDING.
    Returns (center, family, en1, en2)."""
    center, _ag, subject, _levels = setup_operating_center_with_subject(num_levels=1)
    family = create_family(center["id"])
    st1 = create_student(family["id"], full_name="S1")
    st2 = create_student(family["id"], full_name="S2", birthdate="2017-01-01T00:00:00Z")
    en1 = create_and_place_enrollment(center["id"], st1["id"], subject["id"])
    en2 = create_enrollment(center["id"], st2["id"], subject["id"], diagnostic_raw_score=10)
    return center, family, en1, en2


def test_placing_second_sibling_raises_family_sibling_count_to_two():
    """PRD §3.3: "the family's `sibling_count` is recomputed; and the sibling discount
    is re-run across every active enrollment of every student in the family"
    PRD §3.6: "the number of students in the family with at least one active enrollment"

    Placing the second student's enrollment makes sibling_count go 1 -> 2.

    Design: Difficulty/transitive_cascade/enrollment_place_recomputes_sibling_count_then_monthly_rate_depth2
    """
    _c, family, _en1, en2 = _family_first_placed_second_pending()
    place_enrollment(en2["id"])
    fam = validate_success(api.get_family(family["id"], DIRECTOR))
    assert fam["sibling_count"] == 2, f"sibling_count 1 -> 2 after second place, got {fam['sibling_count']}"


def test_placing_second_sibling_re_derives_first_sibling_monthly_rate():
    """PRD §3.3: "the sibling discount is re-run across every active enrollment of every
    student in the family, so each affected enrollment's `monthly_rate_cents` is
    recomputed by the tuition calculation of §3.6."
    PRD §3.6: "a `sibling_count` of exactly two earns a 5 percent discount"

    The first sibling's already-ACTIVE solo enrollment drops from 15000 to
    floor(15000*0.95)=14250 once the second placement raises sibling_count to 2.

    Design: Difficulty/transitive_cascade/enrollment_place_recomputes_sibling_count_then_monthly_rate_depth2
    """
    _c, _family, en1, en2 = _family_first_placed_second_pending()
    place_enrollment(en2["id"])
    fresh1 = validate_success(api.get_enrollment(en1["id"], DIRECTOR))
    fresh2 = validate_success(api.get_enrollment(en2["id"], DIRECTOR))
    assert fresh1["monthly_rate_cents"] == 14250, \
        f"first sibling re-derived to 14250, got {fresh1['monthly_rate_cents']}"
    assert fresh2["monthly_rate_cents"] == 14250, \
        f"second sibling (first subject, sibling 2) -> 14250, got {fresh2['monthly_rate_cents']}"
