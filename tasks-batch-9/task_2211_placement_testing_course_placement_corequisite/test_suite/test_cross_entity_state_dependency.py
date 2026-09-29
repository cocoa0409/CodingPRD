"""Operations whose legality is decided by the state of an entity the request never
names: an attempt gated by its parent session, a registration gated by a
determination reached through the section's course, and a study gated by its
candidate rule.
"""
from test_helpers import (
    ApiErrorId,
    administration_status_payload,
    api_client,
    confirm_seat,
    create_test_attempt_payload,
    drop_registration,
    get_success_data,
    hold_seat,
    mint_determination,
    new_administration,
    new_course,
    new_rule,
    new_student,
    propose_study,
    set_evidence,
    setup_open_section,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import activate_rule, book_attempt, new_active_rule
from test_helpers.test_users import (
    DIRECTOR_1,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_proctor_headers,
    make_registrar_headers,
)

PROCTOR_11 = "proctor-11"

# --------------------------------------------------------------------------- #
# attempt_check_in_and_booking_gated_by_administration_status
# --------------------------------------------------------------------------- #


def _setup_child_attempts_under_a_scheduled_session():
    """A session whose window brackets the logical clock but which is still
    `SCHEDULED`, holding two `BOOKED` attempts.  No determination exists for either
    student, so nothing below the attempt layer can move."""
    session = new_administration(
        PROCTOR_11,
        room_code="T13",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    student_d = new_student(race_ethnicity_code="ASIAN")
    student_e = new_student(race_ethnicity_code="ASIAN")
    attempt_d = book_attempt(student_d["id"], session["id"])
    attempt_e = book_attempt(student_e["id"], session["id"])
    return {
        "session": session,
        "student_d": student_d,
        "student_e": student_e,
        "attempt_d": attempt_d,
        "attempt_e": attempt_e,
    }


def _set_session_status(session_id, target_status):
    return validate_success(
        api_client.set_test_administration_status(
            session_id,
            administration_status_payload(target_status),
            make_proctor_headers(PROCTOR_11),
        )
    )


def test_check_in_is_refused_while_the_parent_session_is_only_scheduled():
    """"That requires the parent session's `status` to be `OPEN`, or the request
    fails with `ERR_ADMINISTRATION_NOT_OPEN`; requires `X-User-ID` to equal the
    session's `proctor_user_id`; and requires the logical clock to sit at or after
    `starts_at` and strictly before `ends_at`."  Only the parent's status is unmet
    here, and the refusal is not a partial transition.

    Design: Difficulty/cross_entity_state_dependency/attempt_check_in_and_booking_gated_by_administration_status
    """
    setup = _setup_child_attempts_under_a_scheduled_session()
    assert setup["session"]["status"] == "SCHEDULED"
    assert setup["attempt_d"]["state"] == "BOOKED"

    proctor = make_proctor_headers(PROCTOR_11)
    validate_error(
        api_client.check_in_test_attempt(setup["attempt_d"]["id"], proctor),
        ApiErrorId.ERR_ADMINISTRATION_NOT_OPEN,
        409,
    )
    unchanged = get_success_data(
        api_client.get_test_attempt(setup["attempt_d"]["id"], proctor)
    )
    assert unchanged["state"] == "BOOKED"

    opened = _set_session_status(setup["session"]["id"], "OPEN")
    assert opened["status"] == "OPEN"
    checked_in = validate_success(
        api_client.check_in_test_attempt(setup["attempt_d"]["id"], proctor)
    )
    assert checked_in["state"] == "CHECKED_IN"


def test_closing_the_session_marks_an_untouched_child_a_no_show():
    """"In the first hop, every attempt against the session whose `state` is `BOOKED`
    moves `BOOKED -> NO_SHOW`, and every attempt whose `state` is `CHECKED_IN` moves
    `CHECKED_IN -> VOIDED` with `void_reason` set to `PROCTOR_ERROR`."  The no-show
    "sets `next_eligible_at` to null, and leaves the attempt in the ordinal pool
    while touching neither `attempt_counts` nor `remaining_attempts`."

    Design: Difficulty/cross_entity_state_dependency/attempt_check_in_and_booking_gated_by_administration_status
    """
    setup = _setup_child_attempts_under_a_scheduled_session()
    proctor = make_proctor_headers(PROCTOR_11)
    _set_session_status(setup["session"]["id"], "OPEN")
    validate_success(api_client.check_in_test_attempt(setup["attempt_d"]["id"], proctor))
    scored = validate_success(
        api_client.score_test_attempt(
            setup["attempt_d"]["id"], {"raw_score": 80}, proctor
        )
    )
    assert scored["state"] == "SCORED"
    assert scored["scaled_score"] == 500

    closed = _set_session_status(setup["session"]["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    # The session "exposes `seats_booked` as the number of attempts against it
    # whose `state` is `BOOKED`, `CHECKED_IN` or `SCORED`" (PRD 3.3): attempt_d
    # is SCORED, and only the untouched attempt_e leaves the count.
    assert closed["seats_booked"] == 1

    staff = make_assessment_staff_headers()
    no_show = get_success_data(
        api_client.get_test_attempt(setup["attempt_e"]["id"], staff)
    )
    assert no_show["state"] == "NO_SHOW"
    assert no_show["next_eligible_at"] is None

    student_e = get_success_data(
        api_client.get_student(setup["student_e"]["id"], staff)
    )
    assert student_e["attempt_counts"]["MATH"] == 0
    assert student_e["remaining_attempts"]["MATH"] == 3

    student_d = get_success_data(
        api_client.get_student(setup["student_d"]["id"], staff)
    )
    assert student_d["attempt_counts"]["MATH"] == 1
    assert student_d["remaining_attempts"]["MATH"] == 2


def test_a_closed_parent_blocks_new_bookings_with_its_own_error():
    """"Booking is refused with `ERR_ADMINISTRATION_NOT_BOOKABLE` when the session's
    `status` is `CLOSED` or `CANCELLED`" -- the same parent-state dependency as
    check-in, on a different endpoint and with a different code.

    Design: Difficulty/cross_entity_state_dependency/attempt_check_in_and_booking_gated_by_administration_status
    """
    setup = _setup_child_attempts_under_a_scheduled_session()
    _set_session_status(setup["session"]["id"], "OPEN")
    _set_session_status(setup["session"]["id"], "CLOSED")

    validate_error(
        api_client.create_test_attempt(
            create_test_attempt_payload(
                setup["student_e"]["id"], setup["session"]["id"]
            ),
            make_assessment_staff_headers(),
        ),
        ApiErrorId.ERR_ADMINISTRATION_NOT_BOOKABLE,
        409,
    )


# --------------------------------------------------------------------------- #
# registration_confirm_gated_by_determination_evidence_and_placement_axes
# --------------------------------------------------------------------------- #


def _setup_disputed_determination_and_open_section():
    """A determination driven to `DISPUTED` before any registration exists, so the
    dispute cascade has nothing to deny, plus an open section of the placed course
    with no requisite edges at all."""
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
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
    section = setup_open_section(
        course_050["id"],
        term_code="2026FA",
        room_code="R901",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(student["id"], subject_area="MATH")
    disputed = set_evidence(
        determination["id"],
        "DISPUTED",
        note="Transcript authenticity under review.",
    )
    return {
        "course_050": course_050,
        "section": section,
        "student": student,
        "determination": determination,
        "disputed": disputed,
    }


def test_a_hold_succeeds_but_the_confirm_fails_on_the_disputed_evidence_axis():
    """"The student must hold a governing determination for the subject area of the
    section's course whose `placement_state` is `PROVISIONAL` or `FINAL` and whose
    `evidence_state` is not `DISPUTED`, or the confirmation is refused with
    `ERR_PLACEMENT_NOT_ACTIONABLE`."  The hold itself consults no determination, so a
    seat can be held that cannot yet be confirmed.

    Design: Difficulty/cross_entity_state_dependency/registration_confirm_gated_by_determination_evidence_and_placement_axes
    """
    setup = _setup_disputed_determination_and_open_section()
    assert setup["determination"]["placement_state"] == "PROVISIONAL"
    assert setup["determination"]["evidence_state"] == "UNVERIFIED"
    assert setup["disputed"]["evidence_state"] == "DISPUTED"
    assert setup["disputed"]["placement_state"] == "PROVISIONAL"

    held = hold_seat(setup["student"]["id"], setup["section"]["id"])
    assert held["state"] == "PENDING"
    assert held["prerequisite_status"] == "SATISFIED"

    validate_error(
        api_client.confirm_registration(held["id"], make_registrar_headers()),
        ApiErrorId.ERR_PLACEMENT_NOT_ACTIONABLE,
        409,
    )


def test_the_same_held_row_confirms_once_a_new_determination_governs():
    """"Finally, the student's previous non-terminal determination in the same
    `subject_area` is superseded: a determination in `placement_state` `PROVISIONAL`
    or `FINAL` moves to `SUPERSEDED` with its `superseded_by_id` pointing at the new
    row."  The disputed row leaves the governing position, and the *same* held
    registration then confirms without being re-created -- proof that the dependency
    is re-derived on every confirmation rather than captured at hold time.

    Design: Difficulty/cross_entity_state_dependency/registration_confirm_gated_by_determination_evidence_and_placement_axes
    """
    setup = _setup_disputed_determination_and_open_section()
    held = hold_seat(setup["student"]["id"], setup["section"]["id"])
    validate_error(
        api_client.confirm_registration(held["id"], make_registrar_headers()),
        ApiErrorId.ERR_PLACEMENT_NOT_ACTIONABLE,
        409,
    )

    second = mint_determination(setup["student"]["id"], subject_area="MATH")
    assert second["placement_state"] == "PROVISIONAL"
    assert second["evidence_state"] != "DISPUTED"

    staff = make_assessment_staff_headers()
    superseded = get_success_data(
        api_client.get_placement_determination(setup["determination"]["id"], staff)
    )
    assert superseded["placement_state"] == "SUPERSEDED"
    assert superseded["superseded_by_id"] == second["id"]
    assert superseded["evidence_state"] == "DISPUTED"

    confirmed = confirm_seat(held["id"])
    assert confirmed["state"] == "ENROLLED"
    assert float(confirmed["term_units_at_confirm"]) == 5.0


def test_the_governing_determination_is_resolved_by_query_not_stored_on_the_row():
    """The confirmation names no determination at all: it requires that "The student
    must hold a governing determination for the subject area of the section's
    course", so the row is found by walking from the section to its course.  A fresh
    hold created after the drop therefore confirms against whichever determination
    currently governs.

    Design: Difficulty/cross_entity_state_dependency/registration_confirm_gated_by_determination_evidence_and_placement_axes
    """
    setup = _setup_disputed_determination_and_open_section()
    held = hold_seat(setup["student"]["id"], setup["section"]["id"])
    mint_determination(setup["student"]["id"], subject_area="MATH")
    confirm_seat(held["id"])

    dropped = drop_registration(held["id"])
    assert dropped["state"] == "DROPPED"

    again = confirm_seat(
        hold_seat(setup["student"]["id"], setup["section"]["id"])["id"]
    )
    assert again["state"] == "ENROLLED"
    assert float(again["term_units_at_confirm"]) == 5.0


# --------------------------------------------------------------------------- #
# study_run_gated_by_candidate_rule_remaining_draft
# --------------------------------------------------------------------------- #


def _setup_studies_over_a_closed_window():
    """Two draft candidate rules on the same course, each with a study over an
    observation window that has already closed; the first rule is then activated,
    which breaks its study's dependency rather than enabling it."""
    course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    rule_a = new_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=500,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V2",
    )
    study_a = propose_study(
        rule_a["id"], "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"
    )
    activated = activate_rule(rule_a["id"])

    rule_b = new_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TEST_SCORE",
        min_score=550,
        priority_rank=20,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V3",
    )
    study_b = propose_study(
        rule_b["id"], "2026-01-01T00:00:00Z", "2026-06-01T00:00:00Z"
    )
    return {
        "course": course,
        "rule_a": rule_a,
        "rule_b": rule_b,
        "study_a": study_a,
        "study_b": study_b,
        "activated": activated,
    }


def _study(study_id):
    return get_success_data(
        api_client.get_validation_study(study_id, make_assessment_staff_headers())
    )


def test_activating_the_candidate_rule_breaks_its_own_study():
    """"Either entry into `RUNNING` requires the candidate rule to still be in
    status `DRAFT`, failing with `ERR_CANDIDATE_RULE_NOT_DRAFT`, and requires the
    observation window to be closed."  The window here is closed and the study's own
    state is a runnable `DRAFT`, yet the parent's promotion out of `DRAFT` refuses
    the run, and the refusal advances nothing.

    Design: Difficulty/cross_entity_state_dependency/study_run_gated_by_candidate_rule_remaining_draft
    """
    setup = _setup_studies_over_a_closed_window()
    assert setup["rule_a"]["status"] == "DRAFT"
    assert setup["study_a"]["state"] == "DRAFT"
    assert setup["study_a"]["run_count"] == 0
    assert setup["activated"]["status"] == "ACTIVE"
    assert setup["activated"]["activated_at"] == "2026-08-01T00:00:00Z"

    validate_error(
        api_client.run_validation_study(
            setup["study_a"]["id"], make_assessment_staff_headers()
        ),
        ApiErrorId.ERR_CANDIDATE_RULE_NOT_DRAFT,
        409,
    )
    after = _study(setup["study_a"]["id"])
    assert after["state"] == "DRAFT"
    assert after["run_count"] == 0


def test_retiring_the_candidate_withdraws_the_study_and_escalates_the_failure():
    """"Retiring a rule from `DRAFT` or from `ACTIVE` also withdraws its studies:
    every cut-score validation study in state `DRAFT`, `RUNNING` or `COMPLETED` whose
    `candidate_rule_id` is this rule moves to `WITHDRAWN` with a `decision_note`
    recorded."  Retirement therefore terminates the dependent study rather than
    repairing it, and the same run request now fails one band higher, on the study's
    own state.

    Design: Difficulty/cross_entity_state_dependency/study_run_gated_by_candidate_rule_remaining_draft
    """
    setup = _setup_studies_over_a_closed_window()
    staff = make_assessment_staff_headers()
    validate_error(
        api_client.run_validation_study(setup["study_a"]["id"], staff),
        ApiErrorId.ERR_CANDIDATE_RULE_NOT_DRAFT,
        409,
    )

    retired = validate_success(
        api_client.retire_placement_rule(
            setup["rule_a"]["id"], make_assessment_director_headers(DIRECTOR_1)
        )
    )
    assert retired["status"] == "RETIRED"

    withdrawn = _study(setup["study_a"]["id"])
    assert withdrawn["state"] == "WITHDRAWN"
    assert withdrawn["run_count"] == 0

    validate_error(
        api_client.run_validation_study(setup["study_a"]["id"], staff),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )


def test_a_draft_candidate_lets_the_run_reach_the_cohort_check():
    """"Reaching `COMPLETED` additionally requires the strict cohort to contain at
    least one row: a strict cohort of size zero aborts the whole request with
    `ERR_STUDY_COHORT_EMPTY` and leaves the study in whatever state it held before
    the call, which is `DRAFT` on a first run."  With the candidate still `DRAFT` the
    request passes the parent-state gate and fails much later, which is what locates
    that gate in the ordered list.

    Design: Difficulty/cross_entity_state_dependency/study_run_gated_by_candidate_rule_remaining_draft
    """
    setup = _setup_studies_over_a_closed_window()
    staff = make_assessment_staff_headers()

    rule_b = get_success_data(
        api_client.get_placement_rule(
            setup["rule_b"]["id"], make_assessment_director_headers()
        )
    )
    assert rule_b["status"] == "DRAFT"

    body = validate_error(
        api_client.run_validation_study(setup["study_b"]["id"], staff),
        ApiErrorId.ERR_STUDY_COHORT_EMPTY,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_CANDIDATE_RULE_NOT_DRAFT
