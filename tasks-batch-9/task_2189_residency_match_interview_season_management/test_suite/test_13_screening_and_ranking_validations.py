"""Field- and rule-level validation refusals on screening, slots and rank lists.

Each test drives one declared validation rule to its boundary and checks both the
refusal code the PRD assigns it and the fact that the refused write left no trace.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    MedicalSchoolType,
    ScreeningDecision,
    ScreeningStatus,
    VisaStatus,
    assert_score_equals,
    build_interview_slot_payload,
    build_rank_list_entry_payload,
    build_screen_payload,
    setup_program,
    setup_reviewed_application,
    setup_screened_application,
)

#: The wave window opens on 2026-10-01T12:00:00Z, so this block sits a day early.
EARLY_SLOT_START_AT = "2026-09-30T13:00:00Z"
EARLY_SLOT_END_AT = "2026-09-30T16:00:00Z"


# ----------------------------------------------------------------------
# Interview block timing
# ----------------------------------------------------------------------
def test_slot_before_its_wave_window_is_a_timing_violation(api):
    """A block one day before its wave opens is refused as a timing violation.

    The block's own end_at is strictly after its start_at and its wave exists, so a
    naive implementation reports a generic shape error; the containment breach has
    its own code and its own status.

    PRD 3.3: "The slot's whole interval must also lie wholly inside its wave's closed window from `invite_release_at` through `response_deadline_at`; a block that pokes out at either end, or whose `end_at` is not strictly after its `start_at`, is refused with `ERR_SLOT_TIMING_VIOLATION`."
    PRD 2.12: "On `POST /interview-slots`, `end_at` is strictly after `start_at` and the whole slot interval lies inside its wave's closed window from `invite_release_at` through `response_deadline_at`."

    Design: Corner/validations/a_slot_starting_before_its_wave_opens_violates_the_slot_timing_rule
    """
    builder = setup_screened_application(1)
    builder.open_interviews()
    builder.create_wave(seat_capacity=1)

    response = api.create_interview_slot(
        build_interview_slot_payload(
            builder.id("wave1"),
            start_at=EARLY_SLOT_START_AT,
            end_at=EARLY_SLOT_END_AT,
            applicant_capacity=1,
        ),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_TIMING_VIOLATION)

    _, meta = validate_paginated(
        api.list_interview_slots(
            builder.coordinator, params={"wave_id": builder.id("wave1")}
        )
    )
    assert meta["total_count"] == 0, (
        "the refused block must not have been created: the wave should hold no slots, "
        f"but the listing reports {meta['total_count']}"
    )


# ----------------------------------------------------------------------
# The evaluation minimum on the screening decision
# ----------------------------------------------------------------------
def test_screening_on_one_review_is_short_of_the_evaluation_minimum(api):
    """One review is not enough to screen, and the refusal writes nothing.

    The single review already refreshed provisional_screen_score, so an
    implementation that screens eagerly would leave a half-written application with
    a final score but no decision.

    PRD 3.2: "An advance decision drives `UNDER_REVIEW → ADVANCED` and a reject decision drives `UNDER_REVIEW → REJECTED`; both require the program to be in `REVIEW_OPEN` and both require `review_count` to be at least 2, the shortfall reported as `ERR_INSUFFICIENT_EVALUATIONS`."
    PRD 2.12: "On `POST /applications/{id}/screen`, the application's `review_count` is at least 2."
    PRD 3.2: "`final_screen_score` is **Variant B**: the base plus the Step 2 band bonus plus the pipeline bonus, then capped at a ceiling of 40.0, then rounded half up to two decimal places once at the end."

    Design: Corner/validations/screening_an_application_that_holds_one_review_is_short_of_the_evaluation_minimum
    """
    builder = setup_reviewed_application(1, review_count=1)

    response = api.screen_application(
        builder.id("app1"),
        build_screen_payload(ScreeningDecision.ADVANCE),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_EVALUATIONS)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["screening_status"] == ScreeningStatus.UNDER_REVIEW, (
        "a refused screen must leave screening_status at UNDER_REVIEW, got "
        f"{application['screening_status']}"
    )
    assert application["review_count"] == 1, (
        f"the application should still hold one review, got {application['review_count']}"
    )
    assert_score_equals(
        application["provisional_screen_score"],
        24.50,
        "Application.provisional_screen_score after one 30/20/20 review",
    )
    assert application["final_screen_score"] is None, (
        "the screening decision writes final_screen_score, so a refused screen must "
        f"leave it null, got {application['final_screen_score']}"
    )


def test_screening_at_exactly_two_reviews_satisfies_the_minimum(api):
    """Exactly two reviews clears the evaluation minimum, so the advance succeeds.

    The threshold is inclusive; an implementation that demands more than two reviews
    would refuse the very case the PRD admits.

    PRD 2.12: "On `POST /applications/{id}/screen`, the application's `review_count` is at least 2."
    PRD 3.2: "An advance decision drives `UNDER_REVIEW → ADVANCED` and a reject decision drives `UNDER_REVIEW → REJECTED`; both require the program to be in `REVIEW_OPEN` and both require `review_count` to be at least 2, the shortfall reported as `ERR_INSUFFICIENT_EVALUATIONS`."

    Design: Corner/validations/screening_at_exactly_two_reviews_satisfies_the_evaluation_minimum
    """
    builder = setup_reviewed_application(1, review_count=2)

    response = api.screen_application(
        builder.id("app1"),
        build_screen_payload(ScreeningDecision.ADVANCE),
        builder.coordinator,
    )
    application = validate_success(response, 200)
    assert application["screening_status"] == ScreeningStatus.ADVANCED, (
        "two reviews must be enough to advance the application, got screening_status "
        f"{application['screening_status']}"
    )
    assert application["review_count"] == 2, (
        f"the application should hold exactly two reviews, got {application['review_count']}"
    )


# ----------------------------------------------------------------------
# The program's declared screening filters
# ----------------------------------------------------------------------
def test_img_applicant_is_refused_by_a_program_that_does_not_accept_img(api):
    """An IMG applicant fails the img_accepted filter on the advance branch only.

    Every other filter passes — the Step 2 score clears the floor and the applicant
    needs no visa sponsorship — so the refusal isolates the IMG limb, and the reject
    branch must still be open because it applies no filter of its own.

    PRD 3.2: "The advance branch additionally enforces the program's three declared filters — the applicant's `step2_score` at or above the program's `min_step2_score`, an `IMG` applicant admitted only when `img_accepted` is true, and an applicant whose `visa_status` is `NEEDS_J1` or `NEEDS_H1B` admitted only when `visa_sponsorship_allowed` is true — and reports any shortfall as `ERR_SCREENING_FILTER_FAILED`."
    PRD 3.2: "The reject branch applies no filter of its own; a candidate who fails a filter is refused advancement, not silently rejected."

    Design: Corner/validations/an_img_applicant_is_refused_by_a_program_that_does_not_accept_img
    """
    builder = setup_program(img_accepted=False, min_step2_score=220)
    builder.add_standard_faculty()
    builder.add_applicant(
        "cand1",
        medical_school_type=MedicalSchoolType.IMG,
        visa_status=VisaStatus.US_CITIZEN,
        step2_score=251,
    )
    builder.open_review()
    builder.add_application("app1", "cand1")
    builder.add_reviews("app1")

    response = api.screen_application(
        builder.id("app1"),
        build_screen_payload(ScreeningDecision.ADVANCE),
        builder.coordinator,
    )
    validate_error(response, ApiErrorId.ERR_SCREENING_FILTER_FAILED)

    application = get_success_data(
        api.get_application(builder.id("app1"), builder.coordinator)
    )
    assert application["screening_status"] == ScreeningStatus.UNDER_REVIEW, (
        "a filter failure must leave the application UNDER_REVIEW, got "
        f"{application['screening_status']}"
    )
    assert application["final_screen_score"] is None, (
        "the refused advance must not write final_screen_score, got "
        f"{application['final_screen_score']}"
    )

    rejected = validate_success(
        api.screen_application(
            builder.id("app1"),
            build_screen_payload(ScreeningDecision.REJECT),
            builder.coordinator,
        ),
        200,
    )
    assert rejected["screening_status"] == ScreeningStatus.REJECTED, (
        "the reject branch applies no filter, so the same application must still be "
        f"rejectable, got screening_status {rejected['screening_status']}"
    )


# ----------------------------------------------------------------------
# The rank list ceiling
# ----------------------------------------------------------------------
def test_eleventh_entry_against_a_one_position_quota_exceeds_the_ceiling(api):
    """A one-position program may rank ten applications and no more.

    The eleventh append carries rank_position 11, which is exactly entry_count plus
    one, and a freshly read version, so the sequence rule and the concurrency guard
    both pass and only the length ceiling can refuse it.

    PRD 3.7: "The list may not grow past `quota_positions` multiplied by 10 entries, refused as `ERR_RANK_LIST_TOO_LONG`."
    PRD 2.12: "On both `POST /rank-lists/{id}/entries` and `POST /rank-lists/{id}/submit-to-committee`, the list's `entry_count` must be at or below `quota_positions` multiplied by 10."

    Design: Corner/validations/the_eleventh_entry_against_a_one_position_quota_exceeds_the_list_ceiling
    """
    builder = setup_program(quota_positions=1)
    builder.add_standard_faculty()
    builder.add_applicants(11)
    builder.open_review()
    for index in range(1, 12):
        builder.add_application(f"app{index}", f"cand{index}")
    builder.add_reviews("app1")
    builder.screen("app1")
    builder.open_interviews()
    builder.open_ranking()
    builder.create_rank_list()
    for index in range(1, 11):
        builder.add_entry(f"entry{index}", f"app{index}", index)

    before = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert before["entry_count"] == 10, (
        f"the list should hold ten entries before the trigger, got {before['entry_count']}"
    )

    response = api.create_rank_list_entry(
        builder.id("rank_list"),
        build_rank_list_entry_payload(builder.id("app11"), 11, before["version"]),
        builder.director("pd"),
    )
    validate_error(response, ApiErrorId.ERR_RANK_LIST_TOO_LONG)

    after = get_success_data(
        api.get_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert after["entry_count"] == 10, (
        f"the refused append must not grow the list, got entry_count {after['entry_count']}"
    )
    _, meta = validate_paginated(
        api.list_entries_of_rank_list(builder.id("rank_list"), builder.director("pd"))
    )
    assert meta["total_count"] == 10, (
        f"the list must still expose exactly ten entries, got {meta['total_count']}"
    )
