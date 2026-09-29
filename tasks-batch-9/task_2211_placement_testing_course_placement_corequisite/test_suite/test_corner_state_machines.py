"""Lifecycle edges taken from the state side: declared opening states, terminal
states re-entered, cyclic return edges, transitions refused from the wrong state,
and the cascades that move a neighbouring row's state without naming it.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    confirm_seat,
    create_registration_payload,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_administration,
    new_course,
    new_override,
    new_requisite,
    new_rule,
    new_section,
    new_student,
    new_support_course,
    pair_sections,
    read_section,
    request_info_payload,
    retire_course,
    section_status_payload,
    set_section_status,
    setup_open_section,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    book_attempt,
    file_appeal,
    open_administration,
    resubmit_appeal,
    score_attempt,
    start_appeal_review,
)
from test_helpers.test_users import (
    INSTRUCTOR_1,
    INSTRUCTOR_2,
    REGISTRAR_1,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_instructor_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_student_headers,
    make_system_admin_headers,
)

PROCTOR_30 = "proctor-30"
PROCTOR_31 = "proctor-31"


def _read_course(course_id):
    return get_success_data(
        api_client.get_course(course_id, make_system_admin_headers())
    )


def _read_rule(rule_id):
    return get_success_data(
        api_client.get_placement_rule(rule_id, make_assessment_director_headers())
    )


def _read_requisite(requisite_id):
    return get_success_data(
        api_client.get_course_requisite(requisite_id, make_system_admin_headers())
    )


def _read_registration(registration_id):
    return get_success_data(
        api_client.get_registration(registration_id, make_registrar_headers())
    )


def _read_override(override_id):
    return get_success_data(
        api_client.get_prerequisite_override(override_id, make_instructor_headers())
    )


def _read_appeal(appeal_id):
    return get_success_data(
        api_client.get_placement_appeal(appeal_id, make_registrar_headers())
    )


def _read_attempt(attempt_id):
    return get_success_data(
        api_client.get_test_attempt(attempt_id, make_assessment_staff_headers())
    )


def _read_student(student_id):
    return get_success_data(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )


# --------------------------------------------------------------------------- #
# newly_created_entities_start_in_their_declared_initial_states
# --------------------------------------------------------------------------- #


def _setup_freshly_created_rows():
    """One row of each kind that carries a state axis, created and never touched
    again: two courses joined by a blocking prerequisite edge, a drafted rule, a
    planned section, a scheduled session and an issued waiver."""
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    reading = new_course(
        course_code="READ-050",
        title="College Reading",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    student = new_student(student_number="SI", race_ethnicity_code="MULTI")
    requisite = new_requisite(
        course_050["id"],
        reading["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    rule = new_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    section = new_section(
        course_050["id"],
        term_code="2026FA",
        room_code="R730",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    administration = new_administration(
        PROCTOR_30,
        room_code="T30",
        subject_area="MATH",
        starts_at="2026-09-05T09:00:00Z",
        ends_at="2026-09-05T11:00:00Z",
        seat_capacity=8,
    )
    override = new_override(
        student["id"],
        course_050["id"],
        requisite["id"],
        justification="Departmental waiver on file.",
        expires_at="2026-12-01T00:00:00Z",
    )
    return {
        "course_050": course_050,
        "reading": reading,
        "student": student,
        "requisite": requisite,
        "rule": rule,
        "section": section,
        "administration": administration,
        "override": override,
    }


def test_a_course_a_requisite_edge_and_a_drafted_rule_open_as_declared():
    """"A new course starts with `status` equal to `ACTIVE`, and its three outcome
    figures initialise to `enrolled_count` of 0, `success_count` of 0 and
    `success_rate` of null."  A requisite edge in turn "begins with `status` equal to
    `ACTIVE`", while "A rule drafted this way starts with `status` equal to `DRAFT`
    and `activated_at` equal to null" -- a rule is the one catalogue row that does not
    open in service.

    Design: Corner/State Machines/newly_created_entities_start_in_their_declared_initial_states
    """
    setup = _setup_freshly_created_rows()

    assert setup["course_050"]["status"] == "ACTIVE"
    assert setup["course_050"]["enrolled_count"] == 0
    assert setup["course_050"]["success_count"] == 0
    assert setup["course_050"]["success_rate"] is None
    assert setup["reading"]["status"] == "ACTIVE"

    assert setup["requisite"]["status"] == "ACTIVE"
    assert setup["requisite"]["requisite_type"] == "PREREQUISITE"
    assert setup["requisite"]["min_grade"] == "C"
    assert setup["requisite"]["enforcement"] == "BLOCKING"

    assert setup["rule"]["status"] == "DRAFT"
    assert setup["rule"]["activated_at"] is None
    assert _read_rule(setup["rule"]["id"])["status"] == "DRAFT"


def test_a_planned_section_a_scheduled_session_and_an_issued_waiver_open_as_declared():
    """"The new section opens with `status` `PLANNED`, `pairing_state` `UNPAIRED`,
    `role_in_pair` `NONE`, `linked_section_id` null, and `seats_taken`, `seats_held`
    and `waitlist_count` all zero."  A session likewise "opens in `status`
    `SCHEDULED`", and a waiver "opens in `state` `ISSUED` with `issued_by_user_id` set
    to the issuing `X-User-ID` and `consumed_by_registration_id` null" -- the issuer
    is taken from the request header, never from the body.

    Design: Corner/State Machines/newly_created_entities_start_in_their_declared_initial_states
    """
    setup = _setup_freshly_created_rows()

    section = setup["section"]
    assert section["status"] == "PLANNED"
    assert section["pairing_state"] == "UNPAIRED"
    assert section["role_in_pair"] == "NONE"
    assert section["linked_section_id"] is None
    assert section["seats_taken"] == 0
    assert section["seats_held"] == 0
    assert section["waitlist_count"] == 0

    administration = setup["administration"]
    assert administration["status"] == "SCHEDULED"
    assert administration["duration_minutes"] == 120
    assert administration["seats_booked"] == 0

    override = setup["override"]
    assert override["state"] == "ISSUED"
    assert override["consumed_by_registration_id"] is None
    assert override["issued_by_user_id"] == INSTRUCTOR_1


# --------------------------------------------------------------------------- #
# manual_no_show_keeps_the_ordinal_slot_and_advances_the_next_tier
# --------------------------------------------------------------------------- #


def _setup_no_show_then_retake():
    """One open session whose window brackets the logical clock, and one student with
    no transcript and no placement, so nothing but the attempt layer can move."""
    administration = new_administration(
        PROCTOR_31,
        room_code="T31",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    session = open_administration(administration["id"], PROCTOR_31)
    student = new_student(student_number="SJ", race_ethnicity_code="NHPI")
    first = book_attempt(student["id"], session["id"])
    return {"session": session, "student": student, "first": first}


def test_a_manual_no_show_nulls_the_gate_and_returns_no_budget():
    """"Marking a `BOOKED` attempt as a no-show advances `BOOKED -> NO_SHOW`, sets
    `next_eligible_at` to null, and leaves the attempt in the ordinal pool while
    touching neither `attempt_counts` nor `remaining_attempts`."  A missed sitting
    therefore costs the student nothing from the retake budget, since "Only `SCORED`
    attempts consume budget; a `NO_SHOW` never does".

    Design: Corner/State Machines/manual_no_show_keeps_the_ordinal_slot_and_advances_the_next_tier
    """
    setup = _setup_no_show_then_retake()
    assert setup["first"]["state"] == "BOOKED"

    no_show = validate_success(
        api_client.no_show_test_attempt(
            setup["first"]["id"], make_proctor_headers(PROCTOR_31)
        )
    )
    assert no_show["state"] == "NO_SHOW"
    assert no_show["next_eligible_at"] is None
    assert no_show["attempt_ordinal"] == 1

    student = _read_student(setup["student"]["id"])
    assert student["attempt_counts"]["MATH"] == 0
    assert student["remaining_attempts"]["MATH"] == 3


def test_the_retained_slot_pushes_the_next_scored_attempt_to_the_thirty_day_tier():
    """"Ordinals are assigned by taking the student's attempts in the subject whose
    `state` is not `VOIDED`, sorting them by `created_at` ascending -- never by `id` --
    and numbering them from one; that pool deliberately retains `NO_SHOW` attempts, so
    a missed sitting still advances the tier applied to the next scored attempt."  The
    tier table reads "a first attempt imposes 14 days, a second attempt imposes 30
    days", so the surviving sitting is gated thirty days out rather than fourteen.

    Design: Corner/State Machines/manual_no_show_keeps_the_ordinal_slot_and_advances_the_next_tier
    """
    setup = _setup_no_show_then_retake()
    validate_success(
        api_client.no_show_test_attempt(
            setup["first"]["id"], make_proctor_headers(PROCTOR_31)
        )
    )

    second = book_attempt(setup["student"]["id"], setup["session"]["id"])
    assert second["state"] == "BOOKED"

    scored = score_attempt(second["id"], 100, PROCTOR_31)
    assert scored["state"] == "SCORED"
    assert scored["scaled_score"] == 625
    assert scored["attempt_ordinal"] == 2
    assert scored["scored_at"] == "2026-08-01T00:00:00Z"
    assert scored["next_eligible_at"] == "2026-08-31T00:00:00Z"

    student = _read_student(setup["student"]["id"])
    assert student["attempt_counts"]["MATH"] == 1
    assert student["remaining_attempts"]["MATH"] == 2
    assert _read_attempt(setup["first"]["id"])["attempt_ordinal"] == 1


# --------------------------------------------------------------------------- #
# activating_a_rule_whose_target_course_is_retired_is_rejected
# --------------------------------------------------------------------------- #


def test_activation_is_refused_against_a_retired_target_and_granted_against_a_live_one():
    """"Referencing a retired course from either `target_course_id` or
    `coreq_course_id` is rejected with `ERR_COURSE_RETIRED`."  The bar sits on
    activation and not on drafting, so a rule may be written against a retired course
    and simply never leave `DRAFT`; the refusal leaves `activated_at` null, while a
    sibling rule on a live course activates in the same fixture and records
    "`activated_at` is set to the logical clock".

    Design: Corner/State Machines/activating_a_rule_whose_target_course_is_retired_is_rejected
    """
    dead_course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    live_course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    retired = retire_course(dead_course["id"])
    assert retired["status"] == "RETIRED"
    assert _read_course(live_course["id"])["status"] == "ACTIVE"

    rule_dead = new_rule(
        dead_course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=3.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    rule_live = new_rule(
        live_course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        max_hs_gpa=3.00,
        priority_rank=20,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    assert rule_dead["status"] == "DRAFT"

    validate_error(
        api_client.activate_placement_rule(
            rule_dead["id"], make_assessment_director_headers()
        ),
        ApiErrorId.ERR_COURSE_RETIRED,
        409,
    )
    unchanged = _read_rule(rule_dead["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["activated_at"] is None

    activated = validate_success(
        api_client.activate_placement_rule(
            rule_live["id"], make_assessment_director_headers()
        )
    )
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] == "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# resubmitting_an_appeal_that_was_never_info_requested_is_rejected
# --------------------------------------------------------------------------- #


def _setup_filed_appeal():
    """A transcript-placed student with a filed appeal asking for the transfer-level
    course, so the review cycle can be driven without any test evidence."""
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
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
        transfer_level=True,
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
        student_number="SK2",
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(student["id"], subject_area="MATH")
    appeal = file_appeal(
        determination["id"],
        course_100["id"],
        headers=make_student_headers(student["id"]),
        grounds="NEW_TRANSCRIPT",
        statement="A verified transcript arrived after my placement.",
    )
    return {
        "course_050": course_050,
        "course_100": course_100,
        "student": student,
        "determination": determination,
        "appeal": appeal,
    }


def test_resubmission_is_refused_from_submitted_and_from_under_review():
    """"The student then supplies a replacement `statement`, moving `INFO_REQUESTED ->
    UNDER_REVIEW`, which increments `revision_round` by one and clears
    `info_request_note`."  `INFO_REQUESTED` is the only declared source, so the same
    call is refused from `SUBMITTED` and from `UNDER_REVIEW` alike, and each refusal
    leaves both the state and the round counter untouched.

    Design: Corner/State Machines/resubmitting_an_appeal_that_was_never_info_requested_is_rejected
    """
    setup = _setup_filed_appeal()
    appeal = setup["appeal"]
    assert appeal["state"] == "SUBMITTED"
    assert appeal["revision_round"] == 0
    assert appeal["filed_at"] == "2026-08-01T00:00:00Z"

    validate_error(
        api_client.resubmit_placement_appeal(
            appeal["id"],
            {"statement": "Attaching the official transcript now."},
            make_registrar_headers(),
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    still_submitted = _read_appeal(appeal["id"])
    assert still_submitted["state"] == "SUBMITTED"
    assert still_submitted["revision_round"] == 0

    reviewed = start_appeal_review(appeal["id"])
    assert reviewed["state"] == "UNDER_REVIEW"
    assert reviewed["reviewed_by_user_id"] == REGISTRAR_1

    validate_error(
        api_client.resubmit_placement_appeal(
            appeal["id"],
            {"statement": "Attaching the official transcript now."},
            make_registrar_headers(),
        ),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    still_under_review = _read_appeal(appeal["id"])
    assert still_under_review["state"] == "UNDER_REVIEW"
    assert still_under_review["revision_round"] == 0


def test_an_information_request_is_what_opens_the_resubmission_edge():
    """"The owning reviewer sends the case back with an `info_request_note`, moving
    `UNDER_REVIEW -> INFO_REQUESTED`."  From there the identical resubmission call
    that was twice refused now lands, and the return leg "increments `revision_round`
    by one and clears `info_request_note`".

    Design: Corner/State Machines/resubmitting_an_appeal_that_was_never_info_requested_is_rejected
    """
    setup = _setup_filed_appeal()
    appeal = setup["appeal"]
    start_appeal_review(appeal["id"])

    requested = validate_success(
        api_client.request_appeal_info(
            appeal["id"],
            request_info_payload("Please attach the official transcript."),
            make_registrar_headers(REGISTRAR_1),
        )
    )
    assert requested["state"] == "INFO_REQUESTED"
    assert requested["info_request_note"] == "Please attach the official transcript."
    assert requested["revision_round"] == 0

    resumed = resubmit_appeal(
        appeal["id"], statement="Attaching the official transcript now."
    )
    assert resumed["state"] == "UNDER_REVIEW"
    assert resumed["revision_round"] == 1
    assert resumed["info_request_note"] is None
    assert resumed["reviewed_by_user_id"] == REGISTRAR_1


# --------------------------------------------------------------------------- #
# retiring_an_already_retired_course_is_rejected_from_the_terminal_state
# --------------------------------------------------------------------------- #


def test_a_second_retire_is_refused_and_the_fan_out_never_reaches_the_far_course():
    """"Retiring a course is the single most consequential catalogue action, and the
    office is protected from doing it carelessly: the course must currently be
    `ACTIVE`, and no section of it may sit in status `PLANNED` or `OPEN`, or the
    request is refused with `ERR_COURSE_HAS_LIVE_SECTIONS`."  The first hop retires
    "every requisite edge that is `ACTIVE` and names this course as either its
    `course_id` or its `requisite_course_id`" and every rule naming it, but the far
    end of a swept edge is a course and is never itself retired.

    Design: Corner/State Machines/retiring_an_already_retired_course_is_rejected_from_the_terminal_state
    """
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    reading = new_course(
        course_code="READ-050",
        title="College Reading",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    requisite = new_requisite(
        course_050["id"],
        reading["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
    )
    rule = new_rule(
        course_050["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )

    retired = retire_course(course_050["id"])
    assert retired["status"] == "RETIRED"
    assert _read_requisite(requisite["id"])["status"] == "RETIRED"
    assert _read_rule(rule["id"])["status"] == "RETIRED"

    validate_error(
        api_client.retire_course(course_050["id"], make_system_admin_headers()),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    assert _read_course(course_050["id"])["status"] == "RETIRED"
    assert _read_course(reading["id"])["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# confirming_an_already_enrolled_registration_is_rejected_on_the_second_call
# --------------------------------------------------------------------------- #


def test_a_second_confirmation_is_refused_and_moves_no_seat():
    """"Finally, seat availability decides which branch the confirmation takes.  When
    `available_seats` for the applicable variant is at least one, the registration
    moves `PENDING -> ENROLLED`: the section's `seats_held` decreases by one and
    `seats_taken` increases by one."  `PENDING` is the only declared source, so the
    second call is refused from `ENROLLED` and the seat ledger is not moved twice.

    Design: Corner/State Machines/confirming_an_already_enrolled_registration_is_rejected_on_the_second_call
    """
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
        room_code="R740",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        student_number="SL2",
        race_ethnicity_code="WHITE",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    mint_determination(student["id"], subject_area="MATH")

    held = hold_seat(student["id"], section["id"])
    enrolled = confirm_seat(held["id"])
    assert enrolled["state"] == "ENROLLED"
    assert float(enrolled["term_units_at_confirm"]) == 5.0

    ledger = read_section(section["id"])
    assert ledger["seats_taken"] == 1
    assert ledger["seats_held"] == 0
    assert ledger["available_seats"] == 4

    validate_error(
        api_client.confirm_registration(held["id"], make_registrar_headers()),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    unchanged = _read_registration(held["id"])
    assert unchanged["state"] == "ENROLLED"
    assert float(unchanged["term_units_at_confirm"]) == 5.0

    after = read_section(section["id"])
    assert after["seats_taken"] == 1
    assert after["seats_held"] == 0
    assert after["available_seats"] == 4


# --------------------------------------------------------------------------- #
# section_reopens_from_closed_and_registrations_resume
# --------------------------------------------------------------------------- #


def _setup_section_with_one_enrolment_and_one_waiting_student():
    """An open section of a course with no requisite edges, holding one confirmed
    enrolment, plus a second placed student who has not yet held a seat."""
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
        room_code="R750",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    students = []
    for number in ("SM2", "SN2"):
        student = new_student(
            student_number=number,
            race_ethnicity_code="ASIAN",
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        mint_determination(student["id"], subject_area="MATH")
        students.append(student)
    confirm_seat(hold_seat(students[0]["id"], section["id"])["id"])
    return {"course_050": course_050, "section": section, "students": students}


def _attempt_hold(student_id, section_id):
    section = read_section(section_id)
    return api_client.create_registration(
        create_registration_payload(student_id, section_id, section["version"]),
        make_registrar_headers(),
    )


def test_closing_moves_no_registration_and_refuses_new_holds_without_a_write():
    """"`OPEN -> CLOSED` transitions no registrations at all: the section simply stops
    accepting new holds, and anyone attempting one thereafter is refused with
    `ERR_SECTION_NOT_OPEN`, while its `ENROLLED` rows remain gradeable."  The refused
    hold is not a mutation, so the section's `version` -- "a monotonically increasing
    counter that increments by one on every mutation of the row" -- does not move.

    Design: Corner/State Machines/section_reopens_from_closed_and_registrations_resume
    """
    setup = _setup_section_with_one_enrolment_and_one_waiting_student()

    closed = set_section_status(setup["section"]["id"], "CLOSED")
    assert closed["status"] == "CLOSED"
    assert closed["seats_taken"] == 1

    before = read_section(setup["section"]["id"])["version"]
    validate_error(
        _attempt_hold(setup["students"][1]["id"], setup["section"]["id"]),
        ApiErrorId.ERR_SECTION_NOT_OPEN,
        409,
    )
    assert read_section(setup["section"]["id"])["version"] == before


def test_the_return_edge_resumes_registration_and_refuses_a_second_reopen():
    """"`CLOSED -> OPEN` is the cyclic return edge, reopening a closed section for
    late registration; it requires the section to actually be `CLOSED`, else
    `ERR_SECTION_NOT_CLOSED`."  The reopened section carries its enrolment forward,
    the previously refused hold now confirms, and driving the same edge a second time
    from `OPEN` is refused by its own code rather than by the generic state error.

    Design: Corner/State Machines/section_reopens_from_closed_and_registrations_resume
    """
    setup = _setup_section_with_one_enrolment_and_one_waiting_student()
    set_section_status(setup["section"]["id"], "CLOSED")

    reopened = set_section_status(setup["section"]["id"], "OPEN")
    assert reopened["status"] == "OPEN"
    assert reopened["seats_taken"] == 1
    assert reopened["available_seats"] == 4

    held = hold_seat(setup["students"][1]["id"], setup["section"]["id"])
    assert held["state"] == "PENDING"
    assert confirm_seat(held["id"])["state"] == "ENROLLED"

    validate_error(
        api_client.set_section_status(
            setup["section"]["id"],
            section_status_payload("OPEN"),
            make_registrar_headers(),
        ),
        ApiErrorId.ERR_SECTION_NOT_CLOSED,
        409,
    )


# --------------------------------------------------------------------------- #
# cancelling_a_support_section_breaks_the_pair_and_closes_the_primary
# --------------------------------------------------------------------------- #


def _setup_paired_pair_with_one_corequisite_enrolment():
    """A transfer-level course paired to its support course under a coreq-requiring
    rule, both halves open, with one student enrolled in the primary and therefore
    also in the support section."""
    primary_course = new_course(
        course_code="MATH-100",
        title="College Algebra",
        subject_area="MATH",
        level_rank=100,
        units=4.0,
        transfer_level=True,
    )
    support_course = new_support_course(
        course_code="MATH-100S",
        title="Algebra Support",
        subject_area="MATH",
        level_rank=90,
        units=2.0,
    )
    new_requisite(
        primary_course["id"], support_course["id"], requisite_type="COREQUISITE"
    )
    new_active_rule(
        primary_course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
        coreq_course_id=support_course["id"],
        coreq_required=True,
    )
    primary = new_section(
        primary_course["id"],
        term_code="2026FA",
        room_code="R820",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    support = new_section(
        support_course["id"],
        term_code="2026FA",
        room_code="R821",
        meets_start_at="2026-09-01T18:00:00Z",
        meets_end_at="2026-09-01T19:00:00Z",
        seat_capacity=5,
    )
    pair_sections(primary["id"], support["id"])
    set_section_status(primary["id"], "OPEN")
    set_section_status(support["id"], "OPEN")

    student = new_student(
        student_number="SO2",
        race_ethnicity_code="HISPANIC",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(student["id"], subject_area="MATH")
    registration = confirm_seat(hold_seat(student["id"], primary["id"])["id"])
    return {
        "primary_course": primary_course,
        "support_course": support_course,
        "primary": primary,
        "support": support,
        "student": student,
        "determination": determination,
        "registration": registration,
    }


def test_the_cancelled_half_breaks_the_pair_and_forces_the_primary_closed():
    """"The first hop ... when the section's `pairing_state` is `PAIRED`, moves
    **both** this section and its linked section `PAIRED -> PAIR_BROKEN` with
    `linked_section_id` retained on each.  The second hop, caused by that break,
    forces a linked section whose `role_in_pair` is `PRIMARY` and whose `status` is
    `OPEN` to move `OPEN -> CLOSED`, since its corequisite support is gone and it must
    take no further corequisite-bearing registrations."

    Design: Corner/State Machines/cancelling_a_support_section_breaks_the_pair_and_closes_the_primary
    """
    setup = _setup_paired_pair_with_one_corequisite_enrolment()
    assert setup["determination"]["placed_course_id"] == setup["primary_course"]["id"]
    assert setup["determination"]["coreq_course_id"] == setup["support_course"]["id"]
    assert setup["registration"]["state"] == "ENROLLED"
    assert float(setup["registration"]["term_units_at_confirm"]) == 6.0
    assert setup["registration"]["coreq_registration_id"] is not None

    cancelled = set_section_status(setup["support"]["id"], "CANCELLED")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["pairing_state"] == "PAIR_BROKEN"
    assert cancelled["linked_section_id"] == setup["primary"]["id"]

    primary = read_section(setup["primary"]["id"])
    assert primary["pairing_state"] == "PAIR_BROKEN"
    assert primary["status"] == "CLOSED"
    assert primary["linked_section_id"] == setup["support"]["id"]
    assert primary["seats_taken"] == 0
    assert primary["available_seats"] == 5


def test_the_cancel_denies_both_halves_of_the_corequisite_pair():
    """"The third hop, caused by the first, moves each denied registration's
    `coreq_registration_id` counterpart in state `PENDING`, `ENROLLED` or `WAITLISTED`
    to `DENIED` with the same `denial_reason`."  The cancelled section's own row is
    denied by the first hop, and the cross-link is what carries the denial back to the
    primary registration -- the link itself is not cleared.

    Design: Corner/State Machines/cancelling_a_support_section_breaks_the_pair_and_closes_the_primary
    """
    setup = _setup_paired_pair_with_one_corequisite_enrolment()
    companion_id = setup["registration"]["coreq_registration_id"]

    set_section_status(setup["support"]["id"], "CANCELLED")

    companion = _read_registration(companion_id)
    assert companion["state"] == "DENIED"
    assert companion["denial_reason"] == "SECTION_CANCELLED"

    primary_row = _read_registration(setup["registration"]["id"])
    assert primary_row["state"] == "DENIED"
    assert primary_row["denial_reason"] == "SECTION_CANCELLED"
    assert primary_row["coreq_registration_id"] == companion_id


# --------------------------------------------------------------------------- #
# override_revoke_reverts_prerequisite_status_on_held_registrations
# --------------------------------------------------------------------------- #


def _setup_two_waived_holds():
    """A blocking prerequisite neither student can satisfy, waived for each of them by
    the same instructor; one hold stays `PENDING` and the other is confirmed, which
    redeems its waiver."""
    reading = new_course(
        course_code="READ-050",
        title="College Reading",
        subject_area="ENGLISH",
        level_rank=50,
        units=3.0,
    )
    course_050 = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    requisite = new_requisite(
        course_050["id"],
        reading["id"],
        requisite_type="PREREQUISITE",
        min_grade="C",
        enforcement="BLOCKING",
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
        room_code="R760",
        meets_start_at="2026-09-01T17:00:00Z",
        meets_end_at="2026-09-01T18:00:00Z",
        seat_capacity=5,
    )
    rows = {}
    for key, number in (("p", "SP2"), ("q", "SQ2")):
        student = new_student(
            student_number=number,
            race_ethnicity_code="BLACK",
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        mint_determination(student["id"], subject_area="MATH")
        override = new_override(
            student["id"],
            course_050["id"],
            requisite["id"],
            actor_id=INSTRUCTOR_1,
            justification="Reading support arranged.",
            expires_at="2026-12-01T00:00:00Z",
        )
        registration = hold_seat(
            student["id"], section["id"], override_id=override["id"]
        )
        rows[key] = {
            "student": student,
            "override": override,
            "registration": registration,
        }
    rows["q"]["registration"] = confirm_seat(rows["q"]["registration"]["id"])
    return {"requisite": requisite, "section": section, "rows": rows}


def test_only_the_issuer_may_revoke_and_the_revocation_re_derives_the_held_closure():
    """"Revocation, `ISSUED -> REVOKED`, is available to an `Instructor` -- but only
    for an override they themselves issued, checked against `issued_by_user_id` and
    refused with `ERR_NOT_OVERRIDE_ISSUER` -- or to a `Registrar`, who may revoke any
    override."  Revocation then "recomputes `prerequisite_status` on every `PENDING`
    or `WAITLISTED` registration that presented the override, typically turning
    `OVERRIDDEN` into `UNMET`", which the downstream confirmation reads as
    `ERR_PREREQUISITE_NOT_MET`.

    Design: Corner/State Machines/override_revoke_reverts_prerequisite_status_on_held_registrations
    """
    setup = _setup_two_waived_holds()
    rows = setup["rows"]
    assert rows["p"]["registration"]["state"] == "PENDING"
    assert rows["p"]["registration"]["prerequisite_status"] == "OVERRIDDEN"
    assert rows["q"]["registration"]["state"] == "ENROLLED"

    validate_error(
        api_client.revoke_prerequisite_override(
            rows["p"]["override"]["id"], make_instructor_headers(INSTRUCTOR_2)
        ),
        ApiErrorId.ERR_NOT_OVERRIDE_ISSUER,
        403,
    )
    assert _read_override(rows["p"]["override"]["id"])["state"] == "ISSUED"

    revoked = validate_success(
        api_client.revoke_prerequisite_override(
            rows["p"]["override"]["id"], make_instructor_headers(INSTRUCTOR_1)
        )
    )
    assert revoked["state"] == "REVOKED"

    recomputed = _read_registration(rows["p"]["registration"]["id"])
    assert recomputed["prerequisite_status"] == "UNMET"
    assert recomputed["state"] == "PENDING"

    validate_error(
        api_client.confirm_registration(
            rows["p"]["registration"]["id"], make_registrar_headers()
        ),
        ApiErrorId.ERR_PREREQUISITE_NOT_MET,
        422,
    )


def test_a_redeemed_waiver_cannot_be_revoked_even_by_a_registrar():
    """"A `CONSUMED` override cannot be revoked: the consuming registration must be
    dropped first, which returns the override to `ISSUED`, and a direct attempt is
    refused with `ERR_OVERRIDE_CONSUMED`."  The state bar outranks the `Registrar`'s
    blanket authority to revoke, and the redemption link survives the refusal.

    Design: Corner/State Machines/override_revoke_reverts_prerequisite_status_on_held_registrations
    """
    setup = _setup_two_waived_holds()
    rows = setup["rows"]
    consumed = _read_override(rows["q"]["override"]["id"])
    assert consumed["state"] == "CONSUMED"
    assert (
        consumed["consumed_by_registration_id"] == rows["q"]["registration"]["id"]
    )

    validate_error(
        api_client.revoke_prerequisite_override(
            rows["q"]["override"]["id"], make_registrar_headers()
        ),
        ApiErrorId.ERR_OVERRIDE_CONSUMED,
        409,
    )

    still_consumed = _read_override(rows["q"]["override"]["id"])
    assert still_consumed["state"] == "CONSUMED"
    assert (
        still_consumed["consumed_by_registration_id"]
        == rows["q"]["registration"]["id"]
    )
