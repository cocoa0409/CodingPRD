"""Requests that violate two enforcement bands at once.

"Requests are validated in a single, strictly ascending priority order. **The
first rule that is violated determines the response, and no later rule is
evaluated.**"  Each pair below is exercised twice: once with both rules broken, to
pin the winner, and once with only the lower-priority rule broken, to prove the
loser is genuinely reachable.
"""
from test_helpers import (
    ApiErrorId,
    administration_status_payload,
    api_client,
    create_test_attempt_payload,
    decide_appeal_payload,
    drop_registration,
    endorse_appeal,
    file_appeal,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_administration,
    new_course,
    new_override,
    new_requisite,
    new_student,
    set_clock,
    setup_open_administration,
    setup_open_section,
    start_appeal_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import book_attempt, confirm_seat, score_attempt
from test_helpers.test_users import (
    DIRECTOR_1,
    INSTRUCTOR_1,
    PROCTOR_1,
    PROCTOR_2,
    REGISTRAR_1,
    REGISTRAR_2,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_instructor_headers,
    make_registrar_headers,
    make_student_headers,
)

# --------------------------------------------------------------------------- #
# booking_state_precedes_retake_waiting_period
# --------------------------------------------------------------------------- #

PROCTOR_3 = "proctor-3"


def _book(student_id, administration_id):
    return api_client.create_test_attempt(
        create_test_attempt_payload(student_id, administration_id),
        make_assessment_staff_headers(),
    )


def _setup_booking_state_versus_retake_gate():
    """One scored attempt setting a 14-day gate, then three later sessions: one
    cancelled and inside the gate, one scheduled and inside the gate, and one
    scheduled exactly on the gate instant."""
    administration_1 = setup_open_administration(
        PROCTOR_1,
        room_code="T01",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    student = new_student(race_ethnicity_code="ASIAN")
    attempt = book_attempt(student["id"], administration_1["id"])
    attempt = score_attempt(attempt["id"], 100)

    cancelled = new_administration(
        PROCTOR_2,
        room_code="T02",
        subject_area="MATH",
        starts_at="2026-08-10T00:00:00Z",
        ends_at="2026-08-10T02:00:00Z",
        seat_capacity=5,
    )
    validate_success(
        api_client.set_test_administration_status(
            cancelled["id"],
            administration_status_payload("CANCELLED"),
            make_assessment_director_headers(DIRECTOR_1),
        )
    )
    inside_gate = new_administration(
        PROCTOR_2,
        room_code="T03",
        subject_area="MATH",
        starts_at="2026-08-10T00:00:00Z",
        ends_at="2026-08-10T02:00:00Z",
        seat_capacity=5,
    )
    on_gate = new_administration(
        PROCTOR_3,
        room_code="T04",
        subject_area="MATH",
        starts_at="2026-08-15T00:00:00Z",
        ends_at="2026-08-15T02:00:00Z",
        seat_capacity=5,
    )
    return {
        "student": student,
        "attempt": attempt,
        "cancelled": cancelled,
        "inside_gate": inside_gate,
        "on_gate": on_gate,
    }


def test_cancelled_session_reports_the_state_code_not_the_retake_gate():
    """Band 8 -- "The target resource sits in a state from which the requested
    transition is declared. Violations report `ERR_INVALID_STATE` (409) unless a
    more specific state code applies, in which case that code is used:
    `ERR_ADMINISTRATION_NOT_BOOKABLE`, ..." -- sits above band 20, "Retake waiting
    period -- otherwise `ERR_RETAKE_WAITING_PERIOD` (422). Applies to attempt
    booking."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_precedes_retake_waiting_period
    """
    setup = _setup_booking_state_versus_retake_gate()
    assert setup["attempt"]["attempt_ordinal"] == 1
    assert setup["attempt"]["next_eligible_at"] == "2026-08-15T00:00:00Z"

    error_id = validate_error(
        _book(setup["student"]["id"], setup["cancelled"]["id"]),
        ApiErrorId.ERR_ADMINISTRATION_NOT_BOOKABLE,
        409,
    )["error_id"]
    assert error_id != ApiErrorId.ERR_RETAKE_WAITING_PERIOD


def test_retake_gate_alone_is_reachable_and_a_gate_instant_booking_succeeds():
    """"Booking a new attempt then consults the latest `next_eligible_at` across
    the student's `SCORED` attempts in the session's subject: the booking is
    allowed when there is no such value at all, or when that latest value falls at
    or before the session's `starts_at`. Equality is permitted -- a gate landing
    exactly on `starts_at` still books. A gate strictly after `starts_at` is refused
    with `ERR_RETAKE_WAITING_PERIOD`."

    Design: Difficulty/priority_pair_validation_conflict/booking_state_precedes_retake_waiting_period
    """
    setup = _setup_booking_state_versus_retake_gate()

    validate_error(
        _book(setup["student"]["id"], setup["inside_gate"]["id"]),
        ApiErrorId.ERR_RETAKE_WAITING_PERIOD,
        422,
    )

    second = validate_success(
        _book(setup["student"]["id"], setup["on_gate"]["id"]), 201
    )
    assert second["state"] == "BOOKED"
    assert second["attempt_ordinal"] == 2
    assert second["next_eligible_at"] is None

    staff = make_assessment_staff_headers()
    student = get_success_data(
        api_client.get_student(setup["student"]["id"], staff)
    )
    assert student["attempt_counts"]["MATH"] == 1
    assert student["remaining_attempts"]["MATH"] == 2

    _, meta = validate_paginated(
        api_client.list_test_attempts(
            staff, params={"student_id": setup["student"]["id"]}
        )
    )
    assert meta["total_count"] == 2


# --------------------------------------------------------------------------- #
# prerequisite_safety_precedes_placement_referential_mismatch
# --------------------------------------------------------------------------- #


def _setup_prerequisite_versus_course_mismatch():
    """A MATH-050 section carrying a blocking prerequisite, one student placed into
    MATH-100 (so the section mismatches their placement) and one placed into
    MATH-050 (so only the prerequisite stands in the way)."""
    reading_course = new_course(
        course_code="READ-050",
        title="Reading Fundamentals",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    course_050 = new_course(
        course_code="MATH-050",
        title="Elementary Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    course_100 = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
    )
    requisite = new_requisite(
        course_050["id"],
        reading_course["id"],
        requisite_type="PREREQUISITE",
        enforcement="BLOCKING",
        min_grade="C",
    )
    new_active_rule(
        course_100["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    new_active_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        max_hs_gpa=3.00,
        priority_rank=20,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    section = setup_open_section(
        course_050["id"],
        term_code="2026FA",
        room_code="R601",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )

    student_l = new_student(
        race_ethnicity_code="WHITE",
        hs_gpa=3.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination_l = mint_determination(student_l["id"], subject_area="MATH")
    student_m = new_student(
        race_ethnicity_code="WHITE",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination_m = mint_determination(student_m["id"], subject_area="MATH")
    held_l = hold_seat(student_l["id"], section["id"])
    return {
        "course_050": course_050,
        "course_100": course_100,
        "requisite": requisite,
        "section": section,
        "student_l": student_l,
        "determination_l": determination_l,
        "student_m": student_m,
        "determination_m": determination_m,
        "held_l": held_l,
    }


def test_unmet_prerequisite_outranks_the_placement_course_mismatch():
    """Band 12 -- "Prerequisite enforcement: the prerequisite closure must not
    evaluate to `UNMET` -- otherwise `ERR_PREREQUISITE_NOT_MET` (422). Applies to
    registration confirmation." -- sits above band 16, "The section's course must be
    the governing determination's `placed_course_id` or its `coreq_course_id` --
    otherwise `ERR_PLACEMENT_COURSE_MISMATCH` (422)."  The refusal leaves the hold
    `PENDING`.

    Design: Difficulty/priority_pair_validation_conflict/prerequisite_safety_precedes_placement_referential_mismatch
    """
    setup = _setup_prerequisite_versus_course_mismatch()
    assert setup["held_l"]["prerequisite_status"] == "UNMET"
    assert setup["determination_l"]["placed_course_id"] == setup["course_100"]["id"]

    body = validate_error(
        api_client.confirm_registration(
            setup["held_l"]["id"], make_registrar_headers()
        ),
        ApiErrorId.ERR_PREREQUISITE_NOT_MET,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_PLACEMENT_COURSE_MISMATCH

    unchanged = get_success_data(
        api_client.get_registration(setup["held_l"]["id"], make_registrar_headers())
    )
    assert unchanged["state"] == "PENDING"


def test_course_mismatch_alone_is_reachable_once_the_prerequisite_is_waived():
    """With the prerequisite waived the closure is `OVERRIDDEN`, so band 12 passes
    and the lower band is reached: "The section's course must be the governing
    determination's `placed_course_id` or its `coreq_course_id` -- otherwise
    `ERR_PLACEMENT_COURSE_MISMATCH` (422)."

    Design: Difficulty/priority_pair_validation_conflict/prerequisite_safety_precedes_placement_referential_mismatch
    """
    setup = _setup_prerequisite_versus_course_mismatch()
    registrar = make_registrar_headers()

    dropped = drop_registration(setup["held_l"]["id"])
    assert dropped["state"] == "DROPPED"

    override_l = new_override(
        setup["student_l"]["id"],
        setup["course_050"]["id"],
        setup["requisite"]["id"],
        expires_at="2026-12-01T00:00:00Z",
    )
    held_again = hold_seat(
        setup["student_l"]["id"],
        setup["section"]["id"],
        override_id=override_l["id"],
    )
    assert held_again["prerequisite_status"] == "OVERRIDDEN"

    validate_error(
        api_client.confirm_registration(held_again["id"], registrar),
        ApiErrorId.ERR_PLACEMENT_COURSE_MISMATCH,
        422,
    )
    still_issued = get_success_data(
        api_client.get_prerequisite_override(
            override_l["id"], make_instructor_headers()
        )
    )
    assert still_issued["state"] == "ISSUED"


def test_a_matching_placement_with_a_waiver_enrols_and_redeems_the_override():
    """Once both bands pass, "the registration moves `PENDING -> ENROLLED` ... any
    presented override moves `ISSUED -> CONSUMED` with
    `consumed_by_registration_id` set to this registration".

    Design: Difficulty/priority_pair_validation_conflict/prerequisite_safety_precedes_placement_referential_mismatch
    """
    setup = _setup_prerequisite_versus_course_mismatch()
    assert setup["determination_m"]["placed_course_id"] == setup["course_050"]["id"]

    override_m = new_override(
        setup["student_m"]["id"],
        setup["course_050"]["id"],
        setup["requisite"]["id"],
        expires_at="2026-12-01T00:00:00Z",
    )
    held_m = hold_seat(
        setup["student_m"]["id"],
        setup["section"]["id"],
        override_id=override_m["id"],
    )
    assert held_m["prerequisite_status"] == "OVERRIDDEN"

    confirmed = confirm_seat(held_m["id"])
    assert confirmed["state"] == "ENROLLED"
    assert float(confirmed["term_units_at_confirm"]) == 5.0

    consumed = get_success_data(
        api_client.get_prerequisite_override(
            override_m["id"], make_instructor_headers()
        )
    )
    assert consumed["state"] == "CONSUMED"
    assert consumed["consumed_by_registration_id"] == confirmed["id"]


# --------------------------------------------------------------------------- #
# appeal_endorsement_state_precedes_reviewer_binding
# --------------------------------------------------------------------------- #


def _decide(appeal_id, actor_id):
    return api_client.decide_placement_appeal(
        appeal_id,
        decide_appeal_payload("GRANT", "Transfer-level readiness accepted."),
        make_registrar_headers(actor_id),
    )


def _setup_endorsement_versus_reviewer_binding():
    """An appeal owned by registrar-1 and still `UNDER_REVIEW`, so a GRANT attempted
    by a different registrar breaks both the state band and the binding band."""
    course_050 = new_course(
        course_code="MATH-050",
        title="Elementary Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    course_100 = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
    )
    new_active_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    student = new_student(
        race_ethnicity_code="MULTI",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(student["id"], subject_area="MATH")

    set_clock("2026-08-02T00:00:00Z")
    appeal = file_appeal(
        determination["id"],
        course_100["id"],
        headers=make_student_headers(student["id"]),
        grounds="OTHER",
        statement=(
            "My coursework since the placement shows transfer-level readiness."
        ),
    )
    appeal = start_appeal_review(appeal["id"], REGISTRAR_1)
    return {
        "course_100": course_100,
        "student": student,
        "determination": determination,
        "appeal": appeal,
    }


def test_missing_endorsement_outranks_the_wrong_reviewer():
    """"A decision of `GRANT` is available **only** from `INSTRUCTOR_ENDORSED`;
    attempting it from any other state, `UNDER_REVIEW` included, is refused with
    `ERR_APPEAL_NOT_ENDORSED`."  Band 8 carries that code and sits above band 11's
    actor-to-resource binding, so a stranger's premature GRANT is told the appeal is
    not endorsed rather than that they are not the reviewer.

    Design: Difficulty/priority_pair_validation_conflict/appeal_endorsement_state_precedes_reviewer_binding
    """
    setup = _setup_endorsement_versus_reviewer_binding()
    assert float(setup["determination"]["base_confidence_score"]) == 31.3
    assert setup["determination"]["determined_by_user_id"] == "staff-1"

    body = validate_error(
        _decide(setup["appeal"]["id"], REGISTRAR_2),
        ApiErrorId.ERR_APPEAL_NOT_ENDORSED,
        409,
    )
    assert body["error_id"] != ApiErrorId.ERR_NOT_APPEAL_REVIEWER

    validate_error(
        _decide(setup["appeal"]["id"], REGISTRAR_1),
        ApiErrorId.ERR_APPEAL_NOT_ENDORSED,
        409,
    )
    unchanged = get_success_data(
        api_client.get_placement_appeal(
            setup["appeal"]["id"], make_registrar_headers()
        )
    )
    assert unchanged["state"] == "UNDER_REVIEW"
    assert unchanged["decided_at"] is None


def test_reviewer_binding_alone_is_reachable_once_the_appeal_is_endorsed():
    """"The decider must be the owner, checked against `reviewed_by_user_id` and
    refused with `ERR_NOT_APPEAL_REVIEWER`."  With the endorsement in place the
    state band passes and only the binding band remains; the owner's GRANT then
    succeeds.

    Design: Difficulty/priority_pair_validation_conflict/appeal_endorsement_state_precedes_reviewer_binding
    """
    setup = _setup_endorsement_versus_reviewer_binding()
    endorsed = endorse_appeal(
        setup["appeal"]["id"],
        INSTRUCTOR_1,
        decision_note="Transfer-level readiness confirmed.",
    )
    assert endorsed["state"] == "INSTRUCTOR_ENDORSED"
    assert endorsed["endorsed_by_user_id"] == INSTRUCTOR_1

    validate_error(
        _decide(setup["appeal"]["id"], REGISTRAR_2),
        ApiErrorId.ERR_NOT_APPEAL_REVIEWER,
        403,
    )
    still_endorsed = get_success_data(
        api_client.get_placement_appeal(
            setup["appeal"]["id"], make_registrar_headers()
        )
    )
    assert still_endorsed["state"] == "INSTRUCTOR_ENDORSED"

    granted = validate_success(_decide(setup["appeal"]["id"], REGISTRAR_1))
    assert granted["state"] == "GRANTED"
    assert granted["minted_determination_id"] is not None
    assert granted["decided_at"] == "2026-08-02T00:00:00Z"

    staff = make_assessment_staff_headers()
    minted = get_success_data(
        api_client.get_placement_determination(
            granted["minted_determination_id"], staff
        )
    )
    assert minted["placed_course_id"] == setup["course_100"]["id"]
    old = get_success_data(
        api_client.get_placement_determination(setup["determination"]["id"], staff)
    )
    assert old["placement_state"] == "SUPERSEDED"
