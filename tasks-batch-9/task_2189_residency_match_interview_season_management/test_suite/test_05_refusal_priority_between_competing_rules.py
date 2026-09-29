"""Requests that break two rules at once, where only one code may be reported.

An already-rejected application that would also fail a screening filter must be
refused on its state, and a conflicted faculty member whose seats also collide in
time must be refused on the conflict.
"""

from __future__ import annotations

from test_helpers import (
    CLOCK_WAVE_RELEASE,
    DIRECTOR_NAME,
    LEAD_INTERVIEWER_NAME,
    MEMBER_INTERVIEWER_NAME,
    ApiErrorId,
    PanelRole,
    ScreeningDecision,
    ScreeningStatus,
    SeasonBuilder,
    assert_load,
    build_interview_assignment_payload,
    build_screen_payload,
    get_success_data,
    setup_staffed_program,
    validate_error,
    validate_paginated,
)

THIRD_INTERVIEWER_NAME = "Cyrus Bell"

#: Both applicants score 210 against a floor of 220, so the advance filter fails.
BELOW_FLOOR_STEP2 = 210
#: Two identical reviews, enough to satisfy the evaluation minimum.
NEUTRAL_REVIEWS = ((20, 20, 20), (20, 20, 20))

SECOND_SLOT_START = "2026-10-05T15:00:00Z"
SECOND_SLOT_END = "2026-10-05T17:00:00Z"


def _rejected_and_pending_applications_below_the_floor():
    """Two twice-reviewed applications below the Step 2 floor, the first rejected."""
    builder = setup_staffed_program(applicant_count=0)
    builder.add_applicant("cand1", full_name="Quinn Adler", step2_score=BELOW_FLOOR_STEP2)
    builder.add_applicant("cand2", full_name="Ruth Vega", step2_score=BELOW_FLOOR_STEP2)
    builder.open_review()
    for index in (1, 2):
        builder.add_application(f"app{index}", f"cand{index}")
        builder.add_reviews(f"app{index}", ("f1", "f2"), NEUTRAL_REVIEWS)
    builder.screen("app1", ScreeningDecision.REJECT)
    return builder


def _conflicted_panel_over_two_overlapping_blocks():
    """Two blocks that overlap by an hour, with the conflicted applicant in the second."""
    builder = SeasonBuilder()
    builder.add_applicant("cand1")
    builder.create_program()
    builder.add_faculty(
        "pd", DIRECTOR_NAME, is_program_director=True, is_committee_member=False
    )
    builder.add_faculty(
        "f1", LEAD_INTERVIEWER_NAME, conflict_applicant_ids=[builder.id("cand1")]
    )
    builder.add_faculty("f2", MEMBER_INTERVIEWER_NAME)
    builder.add_faculty("f3", THIRD_INTERVIEWER_NAME)
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1", ("f2", "f3"), ((30, 20, 20), (34, 24, 18)))
    builder.screen("app1")
    builder.open_interviews()
    builder.create_wave(seat_capacity=4)
    builder.create_slot("slot1", applicant_capacity=4)
    builder.create_slot(
        "slot2",
        start_at=SECOND_SLOT_START,
        end_at=SECOND_SLOT_END,
        room_label="A-2",
        applicant_capacity=4,
    )
    builder.assign("asg1", "slot1", "f1", PanelRole.LEAD)
    builder.assign("asg2", "slot1", "f2", PanelRole.MEMBER)
    builder.clock(CLOCK_WAVE_RELEASE)
    builder.release_wave()
    builder.issue_invitation("inv1", "app1")
    builder.accept_invitation("inv1", "slot2", "cand1")
    return builder


def test_advancing_a_rejected_application_is_refused_on_its_state(api):
    """The rejected application would also fail the floor, but its state answers first.

    State admissibility sits above the screening filters in the refusal order, so
    the filter code is not the one the client sees.

    PRD 2.12: "**Priority 5 — state admissibility.** The target resource is in a state from which the requested transition is declared, and the governing `Program.season_phase` permits the operation."
    PRD 3.1: "`screening_status` tracks paper review only, taking one of `RECEIVED`, `UNDER_REVIEW`, `ADVANCED`, `REJECTED` or `WITHDRAWN`, of which `REJECTED` and `WITHDRAWN` are terminal."

    Design: Difficulty/priority_pair_validation_conflict/state_check_precedes_screening_filter_on_already_rejected_application
    """
    builder = _rejected_and_pending_applications_below_the_floor()

    response = api.screen_application(
        builder.id("app1"),
        build_screen_payload(ScreeningDecision.ADVANCE),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["screening_status"] == ScreeningStatus.REJECTED, (
        "the refused request must leave the terminal state alone, got "
        f"{application['screening_status']}"
    )


def test_advancing_a_reviewable_application_below_the_floor_reports_the_filter(api):
    """The sibling application is in an admissible state, so the filter is reached.

    Same applicant score, same reviews, different current state — and now the
    screening filter is the first failure.

    PRD 3.2: "The advance branch additionally enforces the program's three declared filters — the applicant's `step2_score` at or above the program's `min_step2_score`, an `IMG` applicant admitted only when `img_accepted` is true, and an applicant whose `visa_status` is `NEEDS_J1` or `NEEDS_H1B` admitted only when `visa_sponsorship_allowed` is true — and reports any shortfall as `ERR_SCREENING_FILTER_FAILED`."
    PRD 3.2: "The reject branch applies no filter of its own; a candidate who fails a filter is refused advancement, not silently rejected."

    Design: Difficulty/priority_pair_validation_conflict/state_check_precedes_screening_filter_on_already_rejected_application
    """
    builder = _rejected_and_pending_applications_below_the_floor()

    response = api.screen_application(
        builder.id("app2"),
        build_screen_payload(ScreeningDecision.ADVANCE),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_SCREENING_FILTER_FAILED)

    application = get_success_data(
        api.get_application(builder.id("app2"), builder.coordinator)
    )
    assert application["screening_status"] == ScreeningStatus.UNDER_REVIEW, (
        "a refused advance leaves the paper dimension under review, got "
        f"{application['screening_status']}"
    )


def test_a_conflicted_seat_reports_the_conflict_and_not_the_collision(api):
    """The conflicted member's new seat also collides, yet the conflict answers.

    The member holds a seat on a block that overlaps the target block by an hour,
    so both rules are live — and the conflict rule sits at the earlier priority.

    PRD 2.12: "**Priority 7 — conflict of interest.** On `POST /applications/{id}/reviews` and on `POST /interview-assignments`, the acting or targeted `FacultyMember` does not list the subject `Applicant`'s `id` in `conflict_applicant_ids`."
    PRD 2.11: "A faculty member whose array contains the subject `Applicant`'s `id` may neither author a review of that applicant's application nor take a panel seat on a slot that applicant is booked into."

    Design: Difficulty/priority_pair_validation_conflict/conflict_of_interest_precedes_interviewer_double_booking
    """
    builder = _conflicted_panel_over_two_overlapping_blocks()

    response = api.create_interview_assignment(
        build_interview_assignment_payload(
            builder.id("slot2"), builder.id("f1"), PanelRole.MEMBER
        ),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_CONFLICT_OF_INTEREST)


def test_an_unconflicted_member_with_an_overlapping_seat_is_double_booked(api):
    """The clean member's only problem is the hour of overlap.

    Its existing block runs to 16:00 and the target block starts at 15:00, so the
    half-open intervals share an hour.

    PRD 3.5: "The **double-booking** rule bars a member from holding two `ASSIGNED` seats whose blocks collide in time, and its interval convention is precise: each block's interval **includes** its `start_at` and **excludes** its `end_at`, and **no buffer whatsoever** is added on either side."
    PRD 3.5: "Two blocks collide when those half-open intervals share any instant."

    Design: Difficulty/priority_pair_validation_conflict/conflict_of_interest_precedes_interviewer_double_booking
    """
    builder = _conflicted_panel_over_two_overlapping_blocks()

    response = api.create_interview_assignment(
        build_interview_assignment_payload(
            builder.id("slot2"), builder.id("f2"), PanelRole.MEMBER
        ),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED)


def test_neither_refused_seat_is_created_and_no_load_moves(api):
    """Both refusals are total: the second block stays unstaffed and loads are unchanged.

    The conflicted member still carries only its original lead seat of three
    hours at the lead weight.

    PRD 3.5: "The resulting `InterviewAssignment` is created with `status` `ASSIGNED` — the only other value is `RELEASED` — and immediately triggers a recomputation of that faculty member's `scheduled_load`."
    PRD 3.5: "`scheduled_load` is the **forward-looking** variant: over every `ASSIGNED` assignment of this faculty member whose slot's `status` is `OPEN` or `BOOKED`, take the block's duration in hours multiplied by that seat's role weight, add those products together, and round the total half up to two decimal places once at the end."

    Design: Difficulty/priority_pair_validation_conflict/conflict_of_interest_precedes_interviewer_double_booking
    """
    builder = _conflicted_panel_over_two_overlapping_blocks()

    api.create_interview_assignment(
        build_interview_assignment_payload(
            builder.id("slot2"), builder.id("f1"), PanelRole.MEMBER
        ),
        builder.coordinator,
    )
    api.create_interview_assignment(
        build_interview_assignment_payload(
            builder.id("slot2"), builder.id("f2"), PanelRole.MEMBER
        ),
        builder.coordinator,
    )

    rows, meta = validate_paginated(
        api.list_interview_assignments(
            builder.coordinator, params={"slot_id": builder.id("slot2")}
        )
    )
    assert meta["total_count"] == 0, (
        f"no seat may exist on the second block, got {meta['total_count']}"
    )
    assert rows == []

    conflicted = get_success_data(
        api.get_faculty_member(builder.id("f1"), builder.coordinator)
    )
    assert_load(conflicted, scheduled=4.50, realized=0.00)
