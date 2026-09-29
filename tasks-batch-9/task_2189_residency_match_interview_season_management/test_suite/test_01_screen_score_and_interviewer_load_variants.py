"""Two derived figures that each exist in two deliberately different variants.

The screen score is computed twice from the same reviews — once without bonuses
and once with them — and the interviewer load is computed twice from the same
panel seats over two disjoint slot sets.
"""

from __future__ import annotations

from test_helpers import (
    LEAD_INTERVIEWER_NAME,
    MEMBER_INTERVIEWER_NAME,
    SlotStatus,
    ScreeningStatus,
    assert_load,
    assert_score_equals,
    assert_slot_booking,
    build_screen_payload,
    get_success_data,
    setup_accepted_invitation,
    setup_staffed_program,
    validate_success,
)

#: The two paper reviews the screen-score walk records, deliberately unequal.
FIRST_REVIEW = (30, 20, 20)
SECOND_REVIEW = (34, 24, 18)

#: Base = mean of (30*0.45 + 20*0.30 + 20*0.25) and (34*0.45 + 24*0.30 + 18*0.25).
EXPECTED_BASE = 25.75
#: Base plus the 250-band bonus of 6.0 plus the pipeline bonus of 3.0.
EXPECTED_FINAL = 34.75
EXPECTED_BONUS_GAP = 9.00


def _reviewed_application():
    """A twice-reviewed application whose applicant scores 251 and is an alum."""
    builder = setup_staffed_program()
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1", ("f1", "f2"), (FIRST_REVIEW, SECOND_REVIEW))
    return builder


def test_provisional_score_is_the_bonus_free_variant_of_the_review_base(api):
    """Two reviews in, the provisional figure is the plain weighted base.

    The applicant scores 251 and is a pipeline alum, so nine points of bonus are
    available — none of which may reach the provisional figure.

    PRD 3.2: "Each individual review contributes a raw figure equal to its `academic_points` multiplied by 0.45, plus its `experience_points` multiplied by 0.30, plus its `holistic_points` multiplied by 0.25."
    PRD 3.2: "`provisional_screen_score` is **Variant A**: the base alone, rounded half up to two decimal places, with the rounding applied once at the very end."

    Design: Difficulty/dual_variant_calc/screen_score_provisional_versus_final_on_application
    """
    builder = _reviewed_application()

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )

    assert application["review_count"] == 2, (
        "both submitted reviews should be counted, got review_count "
        f"{application['review_count']}"
    )
    assert_score_equals(
        application["provisional_screen_score"],
        EXPECTED_BASE,
        "Application.provisional_screen_score",
    )
    assert application["final_screen_score"] is None, (
        "final_screen_score is written only by the screening decision, got "
        f"{application['final_screen_score']}"
    )


def test_screening_writes_the_bonus_bearing_variant_over_the_same_reviews(api):
    """The advance decision writes the second variant from identical review data.

    The gap between the two variants is exactly the two bonuses, six points for
    the Step 2 band and three for the pipeline record, with the 40.0 ceiling far
    from binding.

    PRD 3.2: "`final_screen_score` is **Variant B**: the base plus the Step 2 band bonus plus the pipeline bonus, then capped at a ceiling of 40.0, then rounded half up to two decimal places once at the end."
    PRD 3.2: "For identical review data the two variants therefore differ by precisely the sum of the two bonuses, unless the ceiling binds and truncates the difference."

    Design: Difficulty/dual_variant_calc/screen_score_provisional_versus_final_on_application
    """
    builder = _reviewed_application()

    response = api.screen_application(
        builder.id("app1"), build_screen_payload(), builder.coordinator
    )
    screened = validate_success(response)

    assert screened["screening_status"] == ScreeningStatus.ADVANCED, (
        "an advance decision should drive the paper dimension to ADVANCED, got "
        f"{screened['screening_status']}"
    )
    assert_score_equals(
        screened["provisional_screen_score"],
        EXPECTED_BASE,
        "Application.provisional_screen_score",
    )
    assert_score_equals(
        screened["final_screen_score"], EXPECTED_FINAL, "Application.final_screen_score"
    )
    gap = screened["final_screen_score"] - screened["provisional_screen_score"]
    assert_score_equals(
        gap, EXPECTED_BONUS_GAP, "the gap between the final and provisional variants"
    )


def test_scheduled_load_weights_the_lead_seat_above_the_member_seat(api):
    """Before the block runs, both seats carry their role weight undiscounted.

    The block is three hours long and holds four seats of which one is booked,
    but no attendance discount may reach the forward-looking figure.

    PRD 3.5: "The building blocks are two: a block's duration in hours, computed as the exact decimal difference between its `end_at` and its `start_at` expressed in hours, and a seat's role weight, which is 1.5 when the assignment's `panel_role` is `LEAD` and 1.0 when it is `MEMBER`."
    PRD 3.5: "No attendance discount is applied, because for a block that has not yet run the attendance is simply unknown."

    Design: Difficulty/dual_variant_calc/interviewer_load_scheduled_versus_realized_on_faculty_member
    """
    builder = setup_accepted_invitation(
        applicant_count=1, seat_capacity=4, slot_capacity=4
    )

    lead = get_success_data(api.get_faculty_member(builder.id("f1"), builder.coordinator))
    member = get_success_data(
        api.get_faculty_member(builder.id("f2"), builder.coordinator)
    )

    assert lead["full_name"] == LEAD_INTERVIEWER_NAME
    assert member["full_name"] == MEMBER_INTERVIEWER_NAME
    assert_load(lead, scheduled=4.50, realized=0.00)
    assert_load(member, scheduled=3.00, realized=0.00)


def test_completing_the_block_moves_the_lead_seat_into_discounted_realized_load(api):
    """Completion empties the forward figure and fills the retrospective one.

    One applicant of the four seats attended, so the attendance factor is a
    quarter and the lead seat realizes 3.0 hours times 1.5 times 0.25.

    PRD 3.5: "A block's attendance factor is its `booked_count` divided by its `applicant_capacity`."
    PRD 3.5: "Because the completed set and the open-or-booked set never overlap, a half-empty completed block yields a strictly smaller realized contribution than its scheduled contribution had been, and the two figures diverge for identical underlying data by design."

    Design: Difficulty/dual_variant_calc/interviewer_load_scheduled_versus_realized_on_faculty_member
    """
    builder = setup_accepted_invitation(
        applicant_count=1, seat_capacity=4, slot_capacity=4
    )
    builder.clock("2026-10-05T16:30:00Z")

    builder.complete_slot("slot1")

    slot = get_success_data(
        api.get_interview_slot(builder.id("slot1"), builder.coordinator)
    )
    assert_slot_booking(slot, expected_booked=1, expected_status=SlotStatus.COMPLETED)

    lead = get_success_data(api.get_faculty_member(builder.id("f1"), builder.coordinator))
    assert_load(lead, scheduled=0.00, realized=1.13)


def test_the_member_seat_realizes_its_own_weight_at_the_same_attendance_factor(api):
    """The second seat on the same completed block realizes the member weight.

    Both seats share one block and one attendance factor, so the two realized
    figures differ only by the role weight.

    PRD 3.5: "`realized_load` is the **retrospective** variant: over every `ASSIGNED` assignment of this faculty member whose slot's `status` is `COMPLETED`, take the block's duration in hours multiplied by that seat's role weight multiplied by that block's **attendance factor**, add those products together, and round the total half up to two decimal places once at the end."
    PRD 3.5: "Finally, `realized_load` is recomputed for every `FacultyMember` holding an `ASSIGNED` assignment on this slot."

    Design: Difficulty/dual_variant_calc/interviewer_load_scheduled_versus_realized_on_faculty_member
    """
    builder = setup_accepted_invitation(
        applicant_count=1, seat_capacity=4, slot_capacity=4
    )
    builder.clock("2026-10-05T16:30:00Z")

    builder.complete_slot("slot1")

    member = get_success_data(
        api.get_faculty_member(builder.id("f2"), builder.coordinator)
    )
    assert_load(member, scheduled=0.00, realized=0.75)
