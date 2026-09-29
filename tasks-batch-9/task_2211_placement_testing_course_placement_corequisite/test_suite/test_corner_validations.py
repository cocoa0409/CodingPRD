"""The ordered enforcement stack read from the outside in: authentication ahead of
existence, the live-row uniqueness scope, the internal order inside a single
capacity band, the temporal gate ahead of the budget it shares a request with, an
expiry window at its exact closing instant, and a pathway gate that refuses the
winner instead of re-ranking.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    confirm_seat,
    create_appeal_payload,
    create_determination_payload,
    create_registration_payload,
    create_test_attempt_payload,
    current_determination_version,
    current_student_version,
    drop_registration,
    get_success_data,
    hold_seat,
    mint_determination,
    new_active_rule,
    new_administration,
    new_course,
    new_rule,
    new_student,
    read_section,
    set_clock,
    setup_open_section,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    activate_rule,
    book_attempt,
    file_appeal,
    open_administration,
    score_attempt,
)
from test_helpers.test_users import (
    STAFF_1,
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_registrar_headers,
    make_student_headers,
)

PROCTOR_41 = "proctor-41"
PROCTOR_42 = "proctor-42"
PROCTOR_50 = "proctor-50"

# A syntactically valid UUID that names no student record.
UNKNOWN_STUDENT_UUID = "11111111-2222-4333-8444-555555555555"


def _read_student(student_id):
    return get_success_data(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )


def _read_determination(determination_id):
    return get_success_data(
        api_client.get_placement_determination(
            determination_id, make_registrar_headers()
        )
    )


# --------------------------------------------------------------------------- #
# authentication_precedes_every_other_check_including_existence
# --------------------------------------------------------------------------- #


def _setup_one_student_and_nothing_else():
    """A single roster row.  Every probe below aims at that row's own read
    endpoint, so the only thing separating a 401 from a 200 is the header pair."""
    student = new_student(student_number="SA9", race_ethnicity_code="UNKNOWN")
    return {"student": student}


def test_a_missing_or_unrecognised_role_is_answered_before_any_other_check():
    """"A request is rejected with `ERR_UNAUTHENTICATED` (401 Unauthorized) when
    `X-User-Role` is absent or is not one of those seven strings, when `X-User-ID` is
    absent or empty, or when `X-User-Role` is `Student` but `X-User-ID` is not the `id`
    of an existing student record."  A role outside the seven declared spellings is
    therefore unauthenticated, not unauthorized.

    Design: Corner/Validations/authentication_precedes_every_other_check_including_existence
    """
    setup = _setup_one_student_and_nothing_else()
    student_id = setup["student"]["id"]

    no_role = {"X-User-ID": STAFF_1, "Content-Type": "application/json"}
    validate_error(
        api_client.get_student(student_id, no_role),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    invented_role = {
        "X-User-ID": STAFF_1,
        "X-User-Role": "Provost",
        "Content-Type": "application/json",
    }
    body = validate_error(
        api_client.get_student(student_id, invented_role),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    assert body["error_id"] != ApiErrorId.ERR_UNAUTHORIZED

    readable = validate_success(
        api_client.get_student(student_id, make_assessment_staff_headers())
    )
    assert readable["student_number"] == "SA9"


def test_an_unresolvable_student_identity_never_reaches_the_path_lookup():
    """"`X-User-ID` is present and non-empty, and when the role is `Student` it names
    an existing student record -- otherwise `ERR_UNAUTHENTICATED` (401)" sits at
    priority 2, while "Every path parameter resolves to an existing row" sits at
    priority 5, so an unknown acting identity is reported as unauthenticated rather
    than as a missing student.

    Design: Corner/Validations/authentication_precedes_every_other_check_including_existence
    """
    setup = _setup_one_student_and_nothing_else()
    student_id = setup["student"]["id"]

    no_user_id = {"X-User-Role": "AssessmentStaff", "Content-Type": "application/json"}
    validate_error(
        api_client.get_student(student_id, no_user_id),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )

    body = validate_error(
        api_client.get_student(student_id, make_student_headers(UNKNOWN_STUDENT_UUID)),
        ApiErrorId.ERR_UNAUTHENTICATED,
        401,
    )
    assert body["error_id"] != ApiErrorId.ERR_STUDENT_NOT_FOUND
    assert body["error_id"] != ApiErrorId.ERR_UNAUTHORIZED

    validate_error(
        api_client.get_student(NON_EXISTENT_UUID, make_assessment_staff_headers()),
        ApiErrorId.ERR_STUDENT_NOT_FOUND,
        404,
    )

    own_row = validate_success(
        api_client.get_student(student_id, make_student_headers(student_id))
    )
    assert own_row["id"] == student_id
    assert own_row["student_number"] == "SA9"


# --------------------------------------------------------------------------- #
# duplicate_registration_blocked_while_live_and_allowed_after_a_drop
# --------------------------------------------------------------------------- #


def _setup_one_placed_student_and_one_open_section():
    """A course carrying no requisite edges at all, one open section of it, and a
    student holding a governing determination for its subject."""
    course = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    new_active_rule(
        course["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="V1",
    )
    section = setup_open_section(
        course["id"],
        term_code="2026FA",
        room_code="R780",
        meets_start_at="2026-09-01T13:00:00Z",
        meets_end_at="2026-09-01T14:00:00Z",
        seat_capacity=5,
    )
    student = new_student(
        student_number="SDUP",
        race_ethnicity_code="MULTI",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    determination = mint_determination(student["id"], subject_area="MATH")
    return {
        "course": course,
        "section": section,
        "student": student,
        "determination": determination,
    }


def _attempt_hold(student_id, section_id):
    """Hold a seat without unwrapping the response, so a refusal is inspectable."""
    section = read_section(section_id)
    return api_client.create_registration(
        create_registration_payload(student_id, section_id, section["version"]),
        make_registrar_headers(),
    )


def test_a_live_row_blocks_a_second_hold_from_pending_and_from_enrolled():
    """"A student who already holds a registration for that same section in state
    `PENDING`, `ENROLLED`, `WAITLISTED` or `COMPLETED` is refused with
    `ERR_DUPLICATE_REGISTRATION` -- a `DROPPED` or `DENIED` row does not block a fresh
    attempt."  The identical request is refused at both live states.

    Design: Corner/Validations/duplicate_registration_blocked_while_live_and_allowed_after_a_drop
    """
    setup = _setup_one_placed_student_and_one_open_section()
    student_id = setup["student"]["id"]
    section_id = setup["section"]["id"]

    first = hold_seat(student_id, section_id)
    assert first["state"] == "PENDING"

    validate_error(
        _attempt_hold(student_id, section_id),
        ApiErrorId.ERR_DUPLICATE_REGISTRATION,
        409,
    )

    confirmed = confirm_seat(first["id"])
    assert confirmed["state"] == "ENROLLED"

    validate_error(
        _attempt_hold(student_id, section_id),
        ApiErrorId.ERR_DUPLICATE_REGISTRATION,
        409,
    )


def test_a_dropped_row_stops_blocking_and_is_still_retained():
    """"dropping from `PENDING` decrements `seats_held`" and a `DROPPED` row leaves the
    live set, so the same student-and-section pair may be held again; the retired row
    is not deleted, and "A section's registrations may be read as a scoped collection,
    filtered by `state` and returned in `created_at` ascending order".

    Design: Corner/Validations/duplicate_registration_blocked_while_live_and_allowed_after_a_drop
    """
    setup = _setup_one_placed_student_and_one_open_section()
    student_id = setup["student"]["id"]
    section_id = setup["section"]["id"]

    first = hold_seat(student_id, section_id)
    confirm_seat(first["id"])
    dropped = drop_registration(first["id"])
    assert dropped["state"] == "DROPPED"

    released = read_section(section_id)
    assert released["seats_taken"] == 0
    assert released["seats_held"] == 0

    second = validate_success(_attempt_hold(student_id, section_id), 201)
    assert second["state"] == "PENDING"
    assert second["id"] != first["id"]

    rows, meta = validate_paginated(
        api_client.list_section_registrations(section_id, make_registrar_headers())
    )
    assert meta["total_count"] == 2
    assert rows[0]["student_id"] == student_id


# --------------------------------------------------------------------------- #
# booking_refusals_inside_priority_twenty_three_keep_their_declared_order
# --------------------------------------------------------------------------- #


def _setup_a_single_seat_session_and_a_roomy_one():
    """Two open MATH sessions over the same window, in different rooms and under
    different proctors so neither scheduling protection participates: the first seats
    exactly one candidate, the second seats five."""
    single = new_administration(
        PROCTOR_41,
        room_code="T41",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=1,
    )
    roomy = new_administration(
        PROCTOR_42,
        room_code="T42",
        subject_area="MATH",
        starts_at="2026-08-01T00:00:00Z",
        ends_at="2026-08-01T02:00:00Z",
        seat_capacity=5,
    )
    single = open_administration(single["id"], PROCTOR_41)
    roomy = open_administration(roomy["id"], PROCTOR_42)
    first_student = new_student(student_number="SY1", race_ethnicity_code="ASIAN")
    second_student = new_student(student_number="SY2", race_ethnicity_code="BLACK")
    return {
        "single": single,
        "roomy": roomy,
        "first_student": first_student,
        "second_student": second_student,
    }


def _attempt_booking(student_id, administration_id):
    """Book without unwrapping, so the refusal's identifier can be read."""
    return api_client.create_test_attempt(
        create_test_attempt_payload(student_id, administration_id),
        make_assessment_staff_headers(),
    )


def test_an_open_attempt_in_the_subject_answers_before_the_session_is_full():
    """"Retake budget and session capacity, evaluated in this internal order: the
    student must have at least one remaining attempt in the session's subject
    (`ERR_ATTEMPT_LIMIT_REACHED`, 422), the student must not already hold an attempt in
    state `BOOKED` or `CHECKED_IN` in the same subject (`ERR_ATTEMPT_ALREADY_OPEN`,
    422), and the session must not be full (`ERR_ADMINISTRATION_FULL`, 409)."  A
    request violating the middle and the last check reports the middle one.

    Design: Corner/Validations/booking_refusals_inside_priority_twenty_three_keep_their_declared_order
    """
    setup = _setup_a_single_seat_session_and_a_roomy_one()
    first_student = setup["first_student"]["id"]

    booked = validate_success(
        _attempt_booking(first_student, setup["single"]["id"]), 201
    )
    assert booked["state"] == "BOOKED"
    assert booked["subject_area"] == "MATH"

    validate_error(
        _attempt_booking(first_student, setup["roomy"]["id"]),
        ApiErrorId.ERR_ATTEMPT_ALREADY_OPEN,
        422,
    )

    body = validate_error(
        _attempt_booking(first_student, setup["single"]["id"]),
        ApiErrorId.ERR_ATTEMPT_ALREADY_OPEN,
        422,
    )
    assert body["error_id"] != ApiErrorId.ERR_ADMINISTRATION_FULL


def test_capacity_is_the_last_of_the_three_and_only_bites_that_one_session():
    """"Booking is refused ... with `ERR_ADMINISTRATION_FULL` when `seats_booked` has
    already reached `seat_capacity`", and `seats_booked` is "the number of attempts
    against it whose `state` is `BOOKED`, `CHECKED_IN` or `SCORED`" -- a per-session
    figure, so the second candidate books freely into the roomier sitting.

    Design: Corner/Validations/booking_refusals_inside_priority_twenty_three_keep_their_declared_order
    """
    setup = _setup_a_single_seat_session_and_a_roomy_one()
    validate_success(
        _attempt_booking(setup["first_student"]["id"], setup["single"]["id"]), 201
    )

    validate_error(
        _attempt_booking(setup["second_student"]["id"], setup["single"]["id"]),
        ApiErrorId.ERR_ADMINISTRATION_FULL,
        409,
    )

    elsewhere = validate_success(
        _attempt_booking(setup["second_student"]["id"], setup["roomy"]["id"]), 201
    )
    assert elsewhere["state"] == "BOOKED"

    full = get_success_data(
        api_client.get_test_administration(
            setup["single"]["id"], make_assessment_staff_headers()
        )
    )
    assert full["seats_booked"] == 1
    assert full["status"] == "OPEN"


# --------------------------------------------------------------------------- #
# retake_gate_answers_before_the_attempt_limit_when_both_are_violated
# --------------------------------------------------------------------------- #


def _setup_three_scored_sittings_and_two_later_sessions():
    """Five MATH sessions under one proctor, each two hours long on its own UTC day
    and in its own room so neither scheduling protection participates.  The first
    three are sat and scored, exhausting the three-attempt budget and pushing the
    gate out to the 180-day tier; the last two are left `SCHEDULED`, which is still
    bookable, one inside the gate and one beyond it."""
    windows = {
        "first": ("T50", "2026-08-01T00:00:00Z", "2026-08-01T02:00:00Z"),
        "second": ("T51", "2026-08-15T00:00:00Z", "2026-08-15T02:00:00Z"),
        "third": ("T52", "2026-09-15T00:00:00Z", "2026-09-15T02:00:00Z"),
        "beyond_the_gate": ("T53", "2027-04-01T00:00:00Z", "2027-04-01T02:00:00Z"),
        "inside_the_gate": ("T54", "2026-11-01T00:00:00Z", "2026-11-01T02:00:00Z"),
    }
    sessions = {
        label: new_administration(
            PROCTOR_50,
            room_code=room_code,
            subject_area="MATH",
            starts_at=starts_at,
            ends_at=ends_at,
            seat_capacity=5,
        )
        for label, (room_code, starts_at, ends_at) in windows.items()
    }
    student = new_student(student_number="SZL", race_ethnicity_code="WHITE")

    scored = {}
    open_administration(sessions["first"]["id"], PROCTOR_50)
    scored["first"] = score_attempt(
        book_attempt(student["id"], sessions["first"]["id"])["id"], 80, PROCTOR_50
    )

    set_clock("2026-08-15T00:30:00Z")
    open_administration(sessions["second"]["id"], PROCTOR_50)
    scored["second"] = score_attempt(
        book_attempt(student["id"], sessions["second"]["id"])["id"], 80, PROCTOR_50
    )

    set_clock("2026-09-15T00:30:00Z")
    open_administration(sessions["third"]["id"], PROCTOR_50)
    scored["third"] = score_attempt(
        book_attempt(student["id"], sessions["third"]["id"])["id"], 80, PROCTOR_50
    )
    return {"sessions": sessions, "student": student, "scored": scored}


def test_each_scored_sitting_lengthens_the_gate_by_its_own_tier():
    """"The tier is keyed on the attempt's `attempt_ordinal`: a first attempt imposes
    14 days, a second attempt imposes 30 days, and a third or later attempt imposes 180
    days", each measured from "its own `scored_at`".  The second booking was itself
    admitted because "a gate landing exactly on `starts_at` still books".

    Design: Corner/Validations/retake_gate_answers_before_the_attempt_limit_when_both_are_violated
    """
    setup = _setup_three_scored_sittings_and_two_later_sessions()
    scored = setup["scored"]

    assert scored["first"]["scaled_score"] == 500
    assert scored["first"]["attempt_ordinal"] == 1
    assert scored["first"]["next_eligible_at"] == "2026-08-15T00:00:00Z"

    assert scored["second"]["attempt_ordinal"] == 2
    assert scored["second"]["next_eligible_at"] == "2026-09-14T00:30:00Z"

    assert scored["third"]["attempt_ordinal"] == 3
    assert scored["third"]["next_eligible_at"] == "2027-03-14T00:30:00Z"

    student = _read_student(setup["student"]["id"])
    assert student["attempt_counts"]["MATH"] == 3
    assert student["remaining_attempts"]["MATH"] == 0


def test_the_waiting_period_answers_first_and_the_budget_only_beyond_it():
    """"A gate strictly after `starts_at` is refused with `ERR_RETAKE_WAITING_PERIOD`"
    at priority 20, while the exhausted budget is only reached at priority 23, where
    "booking when `remaining_attempts` for the session's subject has fallen to zero is
    refused with `ERR_ATTEMPT_LIMIT_REACHED`".  The same student and the same spent
    budget therefore produce two different identifiers, chosen purely by which sitting
    is aimed at.

    Design: Corner/Validations/retake_gate_answers_before_the_attempt_limit_when_both_are_violated
    """
    setup = _setup_three_scored_sittings_and_two_later_sessions()
    student_id = setup["student"]["id"]
    assert setup["sessions"]["inside_the_gate"]["status"] == "SCHEDULED"
    assert setup["sessions"]["beyond_the_gate"]["status"] == "SCHEDULED"

    validate_error(
        _attempt_booking(student_id, setup["sessions"]["inside_the_gate"]["id"]),
        ApiErrorId.ERR_RETAKE_WAITING_PERIOD,
        422,
    )

    validate_error(
        _attempt_booking(student_id, setup["sessions"]["beyond_the_gate"]["id"]),
        ApiErrorId.ERR_ATTEMPT_LIMIT_REACHED,
        422,
    )

    student = _read_student(student_id)
    assert student["attempt_counts"]["MATH"] == 3
    assert student["remaining_attempts"]["MATH"] == 0

    rows, meta = validate_paginated(
        api_client.list_test_attempts(
            make_assessment_staff_headers(),
            params={"student_id": student_id, "subject_area": "MATH"},
        )
    )
    assert meta["total_count"] == 3
    assert rows[0]["attempt_ordinal"] == 1


# --------------------------------------------------------------------------- #
# appeal_filing_window_closes_exactly_thirty_days_after_the_determination
# --------------------------------------------------------------------------- #


def _setup_two_placements_minted_at_the_same_instant():
    """Two students placed into the same course at the same logical instant, so one
    thirty-day filing window can be probed from either side of its closing edge."""
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
    students = {}
    determinations = {}
    for label, number in (("inside", "SAP1"), ("boundary", "SAP2")):
        students[label] = new_student(
            student_number=number,
            race_ethnicity_code="HISPANIC",
            hs_gpa=2.50,
            hs_transcript_status="VERIFIED",
            transcript_recorded_at="2025-06-01T00:00:00Z",
        )
        determinations[label] = mint_determination(
            students[label]["id"], subject_area="MATH"
        )
    return {
        "course_050": course_050,
        "course_100": course_100,
        "students": students,
        "determinations": determinations,
    }


def _attempt_filing(determination_id, requested_course_id, student_id):
    """File without unwrapping, so a closed window can be read off the response."""
    return api_client.create_placement_appeal(
        create_appeal_payload(
            determination_id,
            requested_course_id,
            current_determination_version(determination_id),
        ),
        make_student_headers(student_id),
    )


def test_one_second_inside_the_filing_window_still_files():
    """"The filing window is thirty days from the determination: once the logical clock
    reaches `determined_at` advanced by thirty days, filing is refused with
    `ERR_APPEAL_WINDOW_CLOSED`."  One second short of that instant the appeal opens
    "in `state` `SUBMITTED` with `revision_round` of 0, `filed_at` set to the logical
    clock", and "Filing drives the determination onto `APPEALED`".

    Design: Corner/Validations/appeal_filing_window_closes_exactly_thirty_days_after_the_determination
    """
    setup = _setup_two_placements_minted_at_the_same_instant()
    determination = setup["determinations"]["inside"]
    assert determination["determined_at"] == "2026-08-01T00:00:00Z"
    assert determination["placement_state"] == "PROVISIONAL"
    assert determination["version"] == 1

    set_clock("2026-08-30T23:59:59Z")
    appeal = file_appeal(
        determination["id"],
        setup["course_100"]["id"],
        headers=make_student_headers(setup["students"]["inside"]["id"]),
    )
    assert appeal["state"] == "SUBMITTED"
    assert appeal["revision_round"] == 0
    assert appeal["filed_at"] == "2026-08-30T23:59:59Z"

    parent = _read_determination(determination["id"])
    assert parent["placement_state"] == "APPEALED"
    assert parent["version"] == 2


def test_the_boundary_instant_is_already_closed_and_leaves_the_parent_untouched():
    """"once the logical clock reaches `determined_at` advanced by thirty days, filing
    is refused with `ERR_APPEAL_WINDOW_CLOSED`" -- the boundary instant itself is
    already outside, and the refusal writes nothing, so the determination keeps the
    `version` a later in-window retry would have to echo.

    Design: Corner/Validations/appeal_filing_window_closes_exactly_thirty_days_after_the_determination
    """
    setup = _setup_two_placements_minted_at_the_same_instant()
    determination = setup["determinations"]["boundary"]
    assert determination["version"] == 1

    set_clock("2026-08-31T00:00:00Z")
    validate_error(
        _attempt_filing(
            determination["id"],
            setup["course_100"]["id"],
            setup["students"]["boundary"]["id"],
        ),
        ApiErrorId.ERR_APPEAL_WINDOW_CLOSED,
        422,
    )

    parent = _read_determination(determination["id"])
    assert parent["placement_state"] == "PROVISIONAL"
    assert parent["version"] == 1


# --------------------------------------------------------------------------- #
# english_learner_gate_refuses_the_winner_instead_of_re_ranking
# --------------------------------------------------------------------------- #


def _setup_english_pathway_rules_and_two_learners():
    """One transfer-level English rule open to everyone, one lower English rule
    restricted to actively-served learners but left `DRAFT`, and one MATH rule open to
    everyone; plus a `NOT_EL` student and an `EL_ACTIVE` student."""
    transfer_english = new_course(
        course_code="ENGL-100",
        title="Composition",
        subject_area="ENGLISH",
        level_rank=100,
        units=3.0,
        transfer_level=True,
    )
    multilingual_english = new_course(
        course_code="ENGL-050",
        title="Composition for Multilingual Writers",
        subject_area="ENGLISH",
        level_rank=80,
        units=4.0,
    )
    math = new_course(
        course_code="MATH-050",
        title="Pre-Algebra",
        subject_area="MATH",
        level_rank=50,
        units=5.0,
    )
    open_to_all = new_active_rule(
        transfer_english["id"],
        subject_area="ENGLISH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="RG",
    )
    learner_only = new_rule(
        multilingual_english["id"],
        subject_area="ENGLISH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=20,
        required_el_status="EL_ACTIVE",
        effective_from="2026-07-01T00:00:00Z",
        version_label="RE",
    )
    math_rule = new_active_rule(
        math["id"],
        subject_area="MATH",
        measure_type="TRANSCRIPT_GPA",
        min_hs_gpa=2.00,
        priority_rank=10,
        effective_from="2026-07-01T00:00:00Z",
        version_label="RM",
    )
    not_el = new_student(
        student_number="SNE",
        race_ethnicity_code="WHITE",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    learner = new_student(
        student_number="SEL",
        race_ethnicity_code="HISPANIC",
        el_status="EL_ACTIVE",
        hs_gpa=2.50,
        hs_transcript_status="VERIFIED",
        transcript_recorded_at="2025-06-01T00:00:00Z",
    )
    return {
        "transfer_english": transfer_english,
        "multilingual_english": multilingual_english,
        "math": math,
        "open_to_all": open_to_all,
        "learner_only": learner_only,
        "math_rule": math_rule,
        "not_el": not_el,
        "learner": learner,
    }


def _mint(student_id, subject_area):
    """Run the selector without unwrapping the response, so a refusal is
    inspectable."""
    return api_client.create_placement_determination(
        create_determination_payload(
            student_id,
            current_student_version(student_id),
            subject_area=subject_area,
        ),
        make_assessment_staff_headers(),
    )


def test_a_null_requirement_places_everyone_and_the_grounds_gate_is_separate():
    """"its `required_el_status` is either null or equal to the student's `el_status`"
    admits a `NOT_EL` student to an unrestricted rule.  The other half of the same
    band is a filing gate: "`grounds` of `EL_PATHWAY` is available only to a student
    whose `el_status` is `EL_ACTIVE` or `EL_EXITED`; a student who is `NOT_EL` claiming
    that ground is refused with `ERR_EL_PATHWAY_VIOLATION`."

    Design: Corner/Validations/english_learner_gate_refuses_the_winner_instead_of_re_ranking
    """
    setup = _setup_english_pathway_rules_and_two_learners()
    assert setup["open_to_all"]["required_el_status"] is None
    assert setup["learner_only"]["status"] == "DRAFT"
    assert setup["not_el"]["el_status"] == "NOT_EL"
    assert setup["learner"]["el_status"] == "EL_ACTIVE"

    placed = validate_success(
        _mint(setup["not_el"]["id"], "ENGLISH"), 201
    )
    assert placed["applied_rule_id"] == setup["open_to_all"]["id"]
    assert placed["placed_course_id"] == setup["transfer_english"]["id"]

    validate_error(
        api_client.create_placement_appeal(
            create_appeal_payload(
                placed["id"],
                setup["multilingual_english"]["id"],
                placed["version"],
                grounds="EL_PATHWAY",
                statement="I want the multilingual writers pathway.",
            ),
            make_student_headers(setup["not_el"]["id"]),
        ),
        ApiErrorId.ERR_EL_PATHWAY_VIOLATION,
        422,
    )


def test_the_gate_refuses_the_winner_and_never_falls_through_to_the_runner_up():
    """"When the student's `el_status` is `EL_ACTIVE` and the requested subject is
    `ENGLISH` or `ESL`, the winning rule's `required_el_status` must itself be
    `EL_ACTIVE`, or the request is refused with `ERR_EL_PATHWAY_VIOLATION`. This gate
    never causes re-ranking: if the top-ranked rule is not pathway-appropriate for an
    actively-served English learner, the whole request is rejected rather than quietly
    falling through to the runner-up."

    Design: Corner/Validations/english_learner_gate_refuses_the_winner_instead_of_re_ranking
    """
    setup = _setup_english_pathway_rules_and_two_learners()
    learner_id = setup["learner"]["id"]

    validate_error(
        _mint(learner_id, "ENGLISH"),
        ApiErrorId.ERR_EL_PATHWAY_VIOLATION,
        422,
    )

    activated = activate_rule(setup["learner_only"]["id"])
    assert activated["status"] == "ACTIVE"

    validate_error(
        _mint(learner_id, "ENGLISH"),
        ApiErrorId.ERR_EL_PATHWAY_VIOLATION,
        422,
    )

    _rows, meta = validate_paginated(
        api_client.list_student_determinations(
            learner_id, make_assessment_staff_headers()
        )
    )
    assert meta["total_count"] == 0


def test_removing_the_winner_places_the_learner_while_math_is_untouched():
    """"A retired rule leaves the selector's candidate set immediately", which is what
    finally lets the pathway-appropriate runner-up win outright.  The gate itself is
    scoped by subject -- it runs only "when ... the requested subject is `ENGLISH` or
    `ESL`" -- so the same learner places in MATH through an unrestricted rule.

    Design: Corner/Validations/english_learner_gate_refuses_the_winner_instead_of_re_ranking
    """
    setup = _setup_english_pathway_rules_and_two_learners()
    learner_id = setup["learner"]["id"]
    activate_rule(setup["learner_only"]["id"])

    retired = validate_success(
        api_client.retire_placement_rule(
            setup["open_to_all"]["id"], make_assessment_director_headers()
        )
    )
    assert retired["status"] == "RETIRED"

    english = validate_success(_mint(learner_id, "ENGLISH"), 201)
    assert english["applied_rule_id"] == setup["learner_only"]["id"]
    assert english["placed_course_id"] == setup["multilingual_english"]["id"]
    assert english["measure_type_used"] == "TRANSCRIPT_GPA"

    math = validate_success(_mint(learner_id, "MATH"), 201)
    assert math["applied_rule_id"] == setup["math_rule"]["id"]
    assert math["placed_course_id"] == setup["math"]["id"]
