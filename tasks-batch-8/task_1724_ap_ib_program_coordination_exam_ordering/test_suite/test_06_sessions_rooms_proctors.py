"""Room and proctor logistics: session scheduling gates (course staffing,
exam window, capacity, accommodation capability, one sitting per course),
half-open room overlap, the 30-minute proctor buffer, the subject-conflict
ban, and the register/cancel seat invariant (PRD §3.3, §3.5).
"""
from test_helpers import (
    COORD,
    ApiErrorId,
    assert_exam_session,
    cancel_registration,
    create_exam_session_payload,
    create_proctor_assignment_payload,
    get_session,
    make_active_course,
    make_course,
    make_open_cycle,
    make_order,
    make_proctor_assignment,
    make_registration,
    make_session,
    make_student,
    make_student_headers,
    make_teacher,
    cancel_session,
    release_proctor_assignment,
    get_order,
    validate_error,
    validate_paginated,
    validate_success,
)

WINDOW_START = "2027-05-03T00:00:00Z"


class TestSessionSchedulingGates:
    def test_session_end_not_strictly_after_start_rejected(self, api):
        """PRD §3.5: "The `end_at` must be strictly after `start_at`, on pain
        of `ERR_INVALID_REQUEST`"

        Design: Corner/entities/session_end_not_after_start_returns_invalid_request
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        res = api.create_exam_session(
            create_exam_session_payload(
                course["id"],
                start_at="2027-05-05T09:00:00Z",
                end_at="2027-05-05T09:00:00Z",
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_session_create_requires_active_course(self, api):
        """PRD §3.5: "The course must be `ACTIVE` — a course with no authorized
        teacher cannot be scheduled, and the attempt is rejected with
        `ERR_TEACHER_NOT_AUTHORIZED`."

        Design: Corner/state_machines/session_create_requires_active_course
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])  # SUSPENDED: no authorization records
        res = api.create_exam_session(
            create_exam_session_payload(course["id"]), COORD
        )
        validate_error(res, ApiErrorId.ERR_TEACHER_NOT_AUTHORIZED, 422)

    def test_session_outside_exam_window_rejected(self, api):
        """PRD §3.5: "the sitting must lie entirely within the course's cycle
        exam window — starting at or after `exam_window_start_at` and ending at
        or before `exam_window_end_at` — otherwise `ERR_OUTSIDE_EXAM_WINDOW`."

        Design: Corner/validations/session_outside_exam_window_rejected
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        res = api.create_exam_session(
            create_exam_session_payload(
                course["id"],
                start_at="2027-04-20T09:00:00Z",
                end_at="2027-04-20T11:00:00Z",
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_OUTSIDE_EXAM_WINDOW, 422)

    def test_second_session_for_course_rejected(self, api):
        """PRD §3.5: "At most one non-cancelled session exists per course, so
        scheduling a second sitting while one is still live is rejected with
        `ERR_DUPLICATE_SESSION`."

        Design: Corner/validations/second_session_for_course_rejected
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        make_session(course["id"], room_name="GYM")
        # Different room and day, no overlap: uniqueness is on the course.
        res = api.create_exam_session(
            create_exam_session_payload(
                course["id"],
                room_name="LAB",
                start_at="2027-05-06T09:00:00Z",
                end_at="2027-05-06T11:00:00Z",
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_SESSION, 409)

    def test_room_must_support_accommodations_when_needed(self, api):
        """PRD §3.5: "When any `REGISTERED` registration of the course carries
        an `accommodation_type` other than `NONE`, the room must be
        accommodation-capable — scheduling with `room_supports_accommodations`
        false is rejected with `ERR_ROOM_NOT_ACCOMMODATION_CAPABLE`."

        Design: Corner/validations/room_not_accommodation_capable_rejected
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        student = make_student(subgroup_code="IEP")
        make_registration(
            student["id"], course["id"], accommodation_type="SEPARATE_ROOM"
        )
        res = api.create_exam_session(
            create_exam_session_payload(
                course["id"], room_supports_accommodations=False
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_ROOM_NOT_ACCOMMODATION_CAPABLE, 422)
        res = api.create_exam_session(
            create_exam_session_payload(
                course["id"], room_supports_accommodations=True
            ),
            COORD,
        )
        session = validate_success(res, 201)
        assert session["status"] == "SCHEDULED"
        assert session["room_supports_accommodations"] is True


class TestRoomCapacityBoundary:
    def test_capacity_equality_fits_then_full(self, api):
        """PRD §3.5: "The `room_capacity` must cover the course's current count
        of `REGISTERED` registrations; equality is allowed, but a capacity even
        one seat short is rejected with `ERR_ROOM_CAPACITY_INSUFFICIENT`."
        PRD §3.3: "if the new registration would push that required seat count
        beyond the session's `room_capacity`, the registration is rejected
        outright with `ERR_SESSION_FULL`."

        Design: Difficulty/boundary_precision_check/room_capacity_exact_equality_fits_then_full
        """
        cycle = make_open_cycle()
        teacher = make_teacher()
        course_1, _, _ = make_active_course(
            cycle["id"], teacher=teacher, subject_code="AP_CALC_BC"
        )
        course_2, _, _ = make_active_course(
            cycle["id"], teacher=teacher, subject_code="AP_BIOLOGY"
        )
        s1 = make_student(full_name="Stu A")
        s2 = make_student(full_name="Stu B")
        s3 = make_student(full_name="Stu C", subgroup_code="FRL")
        make_registration(s1["id"], course_1["id"])
        make_registration(s2["id"], course_1["id"])
        make_registration(s1["id"], course_2["id"])
        make_registration(s3["id"], course_2["id"])
        # Capacity exactly equal to the REGISTERED count fits (inclusive >=).
        session = make_session(course_1["id"], room_name="GYM", room_capacity=2)
        assert_exam_session(session)
        assert session["seats_reserved"] == 2
        # One registration beyond the full SCHEDULED session is rejected.
        res = api.create_registration(
            {"student_id": s3["id"], "course_id": course_1["id"]},
            make_student_headers(s3["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SESSION_FULL, 422)
        # One seat short of the required count is rejected at scheduling.
        res = api.create_exam_session(
            create_exam_session_payload(
                course_2["id"],
                room_name="LAB",
                room_capacity=1,
                start_at="2027-05-06T09:00:00Z",
                end_at="2027-05-06T11:00:00Z",
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_ROOM_CAPACITY_INSUFFICIENT, 422)

    def test_cancellation_frees_the_seat_for_a_waiting_registration(self, api):
        """PRD §3.3: "a `SCHEDULED` session for the course recomputes its
        `seats_reserved` down by 1"
        PRD §3.3: "if the new registration would push that required seat count
        beyond the session's `room_capacity`, the registration is rejected
        outright with `ERR_SESSION_FULL`."

        Design: Difficulty/boundary_precision_check/room_capacity_exact_equality_fits_then_full
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        s1 = make_student(full_name="Stu A")
        s2 = make_student(full_name="Stu B")
        s3 = make_student(full_name="Stu C")
        make_registration(s1["id"], course["id"])
        reg_2 = make_registration(s2["id"], course["id"])
        session = make_session(course["id"], room_capacity=2)
        res = api.create_registration(
            {"student_id": s3["id"], "course_id": course["id"]},
            make_student_headers(s3["id"]),
        )
        validate_error(res, ApiErrorId.ERR_SESSION_FULL, 422)
        # Cancelling a seated registration reopens capacity.
        cancel_registration(reg_2["id"])
        assert get_session(session["id"])["seats_reserved"] == 1
        res = api.create_registration(
            {"student_id": s3["id"], "course_id": course["id"]},
            make_student_headers(s3["id"]),
        )
        registration = validate_success(res, 201)
        assert registration["registration_status"] == "REGISTERED"
        assert get_session(session["id"])["seats_reserved"] == 2


class TestRoomOverlap:
    def test_room_half_open_adjacency_allowed(self, api):
        """PRD §3.5: "if another non-cancelled session with the same
        `room_name` string overlaps the new sitting's time interval, the
        request is rejected with `ERR_ROOM_CONFLICT`. Overlap is evaluated as a
        half-open interval — the new sitting's start through, but not
        including, its end — so two sittings where one ends exactly when the
        other begins are adjacent, not conflicting."

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_allowed
        """
        cycle = make_open_cycle()
        teacher = make_teacher()
        course_1, _, _ = make_active_course(
            cycle["id"], teacher=teacher, subject_code="AP_CALC_BC"
        )
        course_2, _, _ = make_active_course(
            cycle["id"], teacher=teacher, subject_code="AP_BIOLOGY"
        )
        course_3, _, _ = make_active_course(
            cycle["id"], teacher=teacher, subject_code="AP_CHEM"
        )
        make_session(
            course_1["id"],
            room_name="R1",
            start_at="2027-05-05T09:00:00Z",
            end_at="2027-05-05T11:00:00Z",
        )
        # Adjacent (start 11:00 == prior end 11:00): allowed, not a conflict.
        adjacent = make_session(
            course_2["id"],
            room_name="R1",
            start_at="2027-05-05T11:00:00Z",
            end_at="2027-05-05T13:00:00Z",
        )
        assert adjacent["status"] == "SCHEDULED"
        # One minute of real overlap (10:59 < 11:00): rejected.
        res = api.create_exam_session(
            create_exam_session_payload(
                course_3["id"],
                room_name="R1",
                start_at="2027-05-05T10:59:00Z",
                end_at="2027-05-05T12:00:00Z",
            ),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_ROOM_CONFLICT, 409)

    def test_cancelled_session_does_not_block_the_room(self, api):
        """PRD §3.5: "if another non-cancelled session with the same
        `room_name` string overlaps the new sitting's time interval, the
        request is rejected with `ERR_ROOM_CONFLICT`"
        PRD §3.6: "Cancelling a session moves it from `SCHEDULED` to
        `CANCELLED`, a terminal state"

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_allowed
        """
        cycle = make_open_cycle()
        teacher = make_teacher()
        course_1, _, _ = make_active_course(
            cycle["id"], teacher=teacher, subject_code="AP_CALC_BC"
        )
        course_2, _, _ = make_active_course(
            cycle["id"], teacher=teacher, subject_code="AP_BIOLOGY"
        )
        first = make_session(
            course_1["id"],
            room_name="R1",
            start_at="2027-05-05T09:00:00Z",
            end_at="2027-05-05T11:00:00Z",
        )
        cancel_session(first["id"])
        # The CANCELLED sitting no longer occupies the room: the identical
        # window is bookable again.
        second = make_session(
            course_2["id"],
            room_name="R1",
            start_at="2027-05-05T09:00:00Z",
            end_at="2027-05-05T11:00:00Z",
        )
        assert second["status"] == "SCHEDULED"


class TestProctorAssignment:
    def test_duplicate_proctor_assignment_rejected(self, api):
        """PRD §3.5: "the pairing is unique — a teacher who already holds an
        `ASSIGNED` assignment on that session cannot be assigned again
        (`ERR_DUPLICATE_PROCTOR`)."

        Design: Corner/validations/duplicate_proctor_rejected
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        session = make_session(course["id"])
        proctor = make_teacher(full_name="T Proctor", email="proc@x.edu")
        make_proctor_assignment(session["id"], proctor["id"])
        res = api.create_proctor_assignment(
            create_proctor_assignment_payload(session["id"], proctor["id"]), COORD
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_PROCTOR, 409)

    def test_proctor_buffered_gap_boundary(self, api):
        """PRD §3.5: "a teacher may not hold two `ASSIGNED` assignments whose
        session windows are separated by less than 30 minutes — the buffer
        gives proctors travel and reset time, so a gap of 30 minutes or more
        between one session's end and the next session's start is allowed,
        while anything tighter is rejected with `ERR_PROCTOR_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/proctor_buffered_gap_conflict
        """
        cycle = make_open_cycle()
        instructor = make_teacher(full_name="T Auth", email="auth@x.edu")
        course_1, _, _ = make_active_course(
            cycle["id"], teacher=instructor, subject_code="AP_CALC_BC"
        )
        course_2, _, _ = make_active_course(
            cycle["id"], teacher=instructor, subject_code="AP_BIOLOGY"
        )
        course_3, _, _ = make_active_course(
            cycle["id"], teacher=instructor, subject_code="AP_CHEM"
        )
        proctor = make_teacher(full_name="T Proctor", email="proc@x.edu")
        s1 = make_session(
            course_1["id"],
            room_name="P1",
            start_at="2027-05-05T09:00:00Z",
            end_at="2027-05-05T10:00:00Z",
        )
        s2 = make_session(
            course_2["id"],
            room_name="P2",
            start_at="2027-05-05T10:30:00Z",
            end_at="2027-05-05T12:00:00Z",
        )
        s3 = make_session(
            course_3["id"],
            room_name="P3",
            start_at="2027-05-05T10:29:00Z",
            end_at="2027-05-05T12:00:00Z",
        )
        make_proctor_assignment(s1["id"], proctor["id"])
        # Exactly 30 minutes between sessions (10:00 end -> 10:30 start): allowed.
        second = make_proctor_assignment(s2["id"], proctor["id"])
        assert second["status"] == "ASSIGNED"
        # 29 minutes (10:00 end -> 10:29 start): tighter than the buffer.
        res = api.create_proctor_assignment(
            create_proctor_assignment_payload(s3["id"], proctor["id"]), COORD
        )
        validate_error(res, ApiErrorId.ERR_PROCTOR_OVERLAP, 409)

    def test_released_proctor_is_available_for_buffered_window(self, api):
        """PRD §3.5: "releasing it moves it to `RELEASED`, its terminal state,
        making the teacher available for other sessions whose windows had been
        buffer-blocked by this one."

        Design: Difficulty/resource_temporal_overlap/proctor_buffered_gap_conflict
        """
        cycle = make_open_cycle()
        instructor = make_teacher(full_name="T Auth", email="auth@x.edu")
        course_1, _, _ = make_active_course(
            cycle["id"], teacher=instructor, subject_code="AP_CALC_BC"
        )
        course_2, _, _ = make_active_course(
            cycle["id"], teacher=instructor, subject_code="AP_BIOLOGY"
        )
        proctor = make_teacher(full_name="T Proctor", email="proc@x.edu")
        s1 = make_session(
            course_1["id"],
            room_name="P1",
            start_at="2027-05-05T09:00:00Z",
            end_at="2027-05-05T10:00:00Z",
        )
        s2 = make_session(
            course_2["id"],
            room_name="P2",
            start_at="2027-05-05T09:15:00Z",
            end_at="2027-05-05T10:30:00Z",
        )
        first = make_proctor_assignment(s1["id"], proctor["id"])
        # 15-minute gap would be buffer-blocked while the first is ASSIGNED.
        release_proctor_assignment(first["id"])
        assert get_session(s2["id"])["status"] == "SCHEDULED"
        res = api.create_proctor_assignment(
            create_proctor_assignment_payload(s2["id"], proctor["id"]), COORD
        )
        second = validate_success(res, 201)
        assert second["status"] == "ASSIGNED"

    def test_subject_conflict_beats_buffered_overlap(self, api):
        """PRD §2.8: "Every request is validated against a fixed, ordered
        cascade. Earlier failures mask later ones: a request that fails an
        earlier check is rejected with that check's error and never evaluated
        against later checks." Safety gates (step 7) precede temporal gates
        (step 8).
        PRD §3.5: "A teacher who holds an `AUTHORIZED` authorization for the
        session's own course may not proctor it; the attempt is rejected with
        `ERR_PROCTOR_SUBJECT_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/proctor_safety_beats_temporal_overlap
        """
        cycle = make_open_cycle()
        teacher_1 = make_teacher(full_name="T One", email="t1@x.edu")
        teacher_2 = make_teacher(full_name="T Two", email="t2@x.edu")
        course_x, _, _ = make_active_course(
            cycle["id"], teacher=teacher_1, subject_code="AP_CALC_BC"
        )
        course_y, _, _ = make_active_course(
            cycle["id"], teacher=teacher_2, subject_code="AP_BIOLOGY"
        )
        session_x = make_session(
            course_x["id"],
            room_name="ROOMA",
            start_at="2027-05-05T09:00:00Z",
            end_at="2027-05-05T11:00:00Z",
        )
        session_y = make_session(
            course_y["id"],
            room_name="ROOMB",
            start_at="2027-05-05T10:00:00Z",
            end_at="2027-05-05T12:00:00Z",
        )
        # Legal: teacher_1 is not authorized in course_y.
        make_proctor_assignment(session_y["id"], teacher_1["id"])
        # Dual violation: subject conflict (authorized in course_x) AND a
        # 10:00-11:00 buffered overlap with session_y. Safety wins.
        res = api.create_proctor_assignment(
            create_proctor_assignment_payload(session_x["id"], teacher_1["id"]),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_PROCTOR_SUBJECT_CONFLICT, 422)
        # The rejected request persists no assignment row.
        assignments, meta = validate_paginated(
            api.list_proctor_assignments(
                COORD,
                params={"session_id": session_x["id"], "teacher_id": teacher_1["id"]},
            )
        )
        assert assignments == []
        assert meta["total_count"] == 0

    def test_subject_conflict_alone_rejected(self, api):
        """PRD §3.5: "A teacher who holds an `AUTHORIZED` authorization for the
        session's own course may not proctor it; the attempt is rejected with
        `ERR_PROCTOR_SUBJECT_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/proctor_safety_beats_temporal_overlap
        """
        cycle = make_open_cycle()
        course, instructor, _ = make_active_course(cycle["id"])
        session = make_session(course["id"])
        # The instructor holds no other assignment: only the conflict-of-
        # interest gate can fire.
        res = api.create_proctor_assignment(
            create_proctor_assignment_payload(session["id"], instructor["id"]),
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_PROCTOR_SUBJECT_CONFLICT, 422)


class TestSeatInvariant:
    def test_register_cancel_pair_conserves_seats_and_estimate(self, api):
        """PRD §3.5: "A created session starts in `SCHEDULED` status, with
        `seats_reserved` equal to the course's count of `REGISTERED`
        registrations; that figure keeps tracking the course's registered
        headcount on every registration creation and cancellation while the
        session remains scheduled."
        PRD §3.4: "its `lines` ... and its `estimate_total_cents` are computed
        live and recomputed on every registration creation or cancellation"

        Design: Difficulty/compensating_invariant/register_cancel_conserves_session_seats
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"], exam_fee_cents=9800)
        s0 = make_student(full_name="Stu Zero")
        s1 = make_student(full_name="Stu One", subgroup_code="FRL")
        make_registration(s0["id"], course["id"])
        order = make_order(cycle["id"])
        session = make_session(course["id"], room_capacity=5)
        # Pre-pair state.
        assert get_session(session["id"])["seats_reserved"] == 1
        assert get_order(order["id"])["estimate_total_cents"] == 9800
        extra = make_registration(s1["id"], course["id"])
        assert get_session(session["id"])["seats_reserved"] == 2
        assert get_order(order["id"])["estimate_total_cents"] == 19600
        cancel_registration(extra["id"])
        # The pair leaves seats and the draft estimate bit-identical.
        session = get_session(session["id"])
        assert session["seats_reserved"] == 1
        assert session["status"] == "SCHEDULED"
        assert get_order(order["id"])["estimate_total_cents"] == 9800

    def test_seats_reserved_tracks_each_new_registration(self, api):
        """PRD §3.5: "that figure keeps tracking the course's registered
        headcount on every registration creation and cancellation while the
        session remains scheduled."

        Design: Difficulty/compensating_invariant/register_cancel_conserves_session_seats
        """
        cycle = make_open_cycle()
        course, _, _ = make_active_course(cycle["id"])
        session = make_session(course["id"], room_capacity=5)
        assert session["seats_reserved"] == 0
        students = [make_student(full_name=f"Stu {i}") for i in range(3)]
        for expected, student in enumerate(students, start=1):
            make_registration(student["id"], course["id"])
            assert get_session(session["id"])["seats_reserved"] == expected
        assert get_session(session["id"])["status"] == "SCHEDULED"
