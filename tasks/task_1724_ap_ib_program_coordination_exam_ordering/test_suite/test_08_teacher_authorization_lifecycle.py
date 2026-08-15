"""Teacher authorization loop: attestation stamps, the 730-day validity
horizon, the inclusive expiry sweep, retraining on the same row, the
depth-3 suspension cascade, and pair uniqueness (PRD §3.2).
"""
from test_helpers import (
    COORD,
    ApiErrorId,
    assert_instant_equal,
    complete_training,
    create_teacher_authorization_payload,
    get_authorization,
    get_course,
    get_proctor_assignment,
    get_registration,
    get_session,
    make_authorization,
    make_course,
    make_open_cycle,
    make_proctor_assignment,
    make_registration,
    make_session,
    make_student,
    make_teacher,
    set_clock,
    validate_error,
)


class TestAuthorizationUniqueness:
    def test_duplicate_authorization_rejected(self, api):
        """PRD §3.2: "At most one authorization row ever exists for a given
        teacher-and-course pair — even an expired row counts — so a duplicate
        open attempt is rejected with `ERR_DUPLICATE_AUTHORIZATION`; retraining
        always happens on the existing row."

        Design: Corner/validations/duplicate_authorization_rejected
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        teacher = make_teacher()
        make_authorization(teacher["id"], course["id"])
        res = api.create_teacher_authorization(
            create_teacher_authorization_payload(teacher["id"], course["id"]), COORD
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_AUTHORIZATION, 409)


class TestExpiryAndRetraining:
    def test_expiry_retrain_full_cycle_with_inclusive_boundary(self, api):
        """PRD §3.2: "A successful attestation moves the record from
        `PENDING_TRAINING` to `AUTHORIZED`, stamps `training_completed_at` with
        the current logical-clock reading, and sets `authorized_until` to
        exactly 730 days after `training_completed_at`."
        PRD §3.2: "every authorization record still in `AUTHORIZED` status
        whose `authorized_until` is at or before the new clock reading
        transitions to `EXPIRED` — the boundary is inclusive, so an
        authorization whose `authorized_until` equals the new time exactly
        counts as expired."
        PRD §3.2: "the teacher may attest retraining on the same record, moving
        it from `EXPIRED` back to `AUTHORIZED` with a fresh
        `training_completed_at`, a fresh 730-day validity horizon"

        Design: Difficulty/non_linear_state_machine/teacher_authorization_expiry_retrain_cycle
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        teacher = make_teacher()
        auth = make_authorization(teacher["id"], course["id"])
        assert auth["status"] == "PENDING_TRAINING"
        assert auth["training_completed_at"] is None
        assert auth["authorized_until"] is None
        # Attest at logical 2026-09-01: validity runs 730 days to 2028-08-31.
        set_clock("2026-09-01T00:00:00Z")
        authorized = complete_training(auth["id"], teacher["id"])
        assert authorized["status"] == "AUTHORIZED"
        assert_instant_equal(
            authorized["training_completed_at"], "2026-09-01T00:00:00Z"
        )
        assert_instant_equal(
            authorized["authorized_until"], "2028-08-31T00:00:00Z"
        )
        assert get_course(course["id"])["status"] == "ACTIVE"
        # One day before the boundary: still AUTHORIZED.
        set_clock("2028-08-30T00:00:00Z")
        assert get_authorization(auth["id"])["status"] == "AUTHORIZED"
        # Exactly AT authorized_until: inclusive boundary expires the record.
        set_clock("2028-08-31T00:00:00Z")
        expired = get_authorization(auth["id"])
        assert expired["status"] == "EXPIRED"
        course = get_course(course["id"])
        assert course["authorized_teacher_count"] == 0
        assert course["status"] == "SUSPENDED"
        # Retraining closes the loop on the same row: EXPIRED -> AUTHORIZED
        # with a fresh 730-day horizon (2028-08-31 + 730d = 2030-08-31).
        retrained = complete_training(auth["id"], teacher["id"])
        assert retrained["status"] == "AUTHORIZED"
        assert_instant_equal(
            retrained["training_completed_at"], "2028-08-31T00:00:00Z"
        )
        assert_instant_equal(
            retrained["authorized_until"], "2030-08-31T00:00:00Z"
        )
        course = get_course(course["id"])
        assert course["authorized_teacher_count"] == 1
        assert course["status"] == "ACTIVE"

    def test_expiry_decrements_without_suspending_until_count_hits_zero(self, api):
        """PRD §3.2: "Each expiry decrements the course's
        `authorized_teacher_count`, and when that takes the count from 1 to 0
        the course flips from `ACTIVE` back to `SUSPENDED`."
        PRD §3.2: "a course is `ACTIVE` when its `authorized_teacher_count` —
        the number of authorization records for the course currently in
        `AUTHORIZED` status — is at least 1, and `SUSPENDED` otherwise."

        Design: Difficulty/non_linear_state_machine/teacher_authorization_expiry_retrain_cycle
        """
        cycle = make_open_cycle()
        course = make_course(cycle["id"])
        teacher_1 = make_teacher(full_name="T One", email="t1@x.edu")
        teacher_2 = make_teacher(full_name="T Two", email="t2@x.edu")
        # t1 authorized at 2026-09-01 (until 2028-08-31); t2 one day later
        # (until 2028-09-01).
        set_clock("2026-09-01T00:00:00Z")
        auth_1 = make_authorization(teacher_1["id"], course["id"])
        complete_training(auth_1["id"], teacher_1["id"])
        set_clock("2026-09-02T00:00:00Z")
        auth_2 = make_authorization(teacher_2["id"], course["id"])
        complete_training(auth_2["id"], teacher_2["id"])
        course = get_course(course["id"])
        assert course["authorized_teacher_count"] == 2
        assert course["status"] == "ACTIVE"
        # First expiry (2 -> 1): the course stays ACTIVE.
        set_clock("2028-08-31T00:00:00Z")
        assert get_authorization(auth_1["id"])["status"] == "EXPIRED"
        assert get_authorization(auth_2["id"])["status"] == "AUTHORIZED"
        course = get_course(course["id"])
        assert course["authorized_teacher_count"] == 1
        assert course["status"] == "ACTIVE"
        # Second expiry (1 -> 0): the course flips to SUSPENDED.
        set_clock("2028-09-01T00:00:00Z")
        assert get_authorization(auth_2["id"])["status"] == "EXPIRED"
        course = get_course(course["id"])
        assert course["authorized_teacher_count"] == 0
        assert course["status"] == "SUSPENDED"


class TestExpiryCascade:
    def _build_cascade_scenario(self, api):
        """ACTIVE course via t1 (authorized 2026-09-01, until 2028-08-31), one
        registration, a SCHEDULED session, and an ASSIGNED proctor."""
        cycle = make_open_cycle()
        course = make_course(cycle["id"], subject_code="AP_CALC_BC")
        instructor = make_teacher(full_name="T Instructor", email="inst@x.edu")
        proctor = make_teacher(full_name="T Proctor", email="proc@x.edu")
        auth = make_authorization(instructor["id"], course["id"])
        set_clock("2026-09-01T00:00:00Z")
        complete_training(auth["id"], instructor["id"])
        student = make_student()
        registration = make_registration(student["id"], course["id"])
        session = make_session(
            course["id"], room_name="LAB", room_capacity=5
        )
        assignment = make_proctor_assignment(session["id"], proctor["id"])
        return cycle, course, auth, registration, session, assignment

    def test_clock_sweep_expiry_cascades_three_levels(self, api):
        """PRD §3.2: "That suspension cascades: every session of the course
        still in `SCHEDULED` status is cancelled, each cancelled session's
        `ASSIGNED` proctor assignments are released, and the students'
        registrations are deliberately left untouched — students remain
        registered even though their sitting is gone."
        PRD §2.4: "Every clock advance runs the teacher-authorization expiry
        sweep described in §3.2 before the response is returned, so cascading
        expirations are already visible by the time the caller sees the new
        time."

        Design: Difficulty/transitive_cascade/clock_sweep_expiry_cascade_depth3
        """
        cycle, course, auth, registration, session, assignment = (
            self._build_cascade_scenario(api)
        )
        # The sweep fires when the clock reaches authorized_until (inclusive).
        set_clock("2028-08-31T00:00:00Z")
        # Link 1: the authorization expires, mutating the course.
        assert get_authorization(auth["id"])["status"] == "EXPIRED"
        course = get_course(course["id"])
        assert course["authorized_teacher_count"] == 0
        assert course["status"] == "SUSPENDED"
        # Link 2: the suspension cancels the SCHEDULED session.
        assert get_session(session["id"])["status"] == "CANCELLED"
        # Link 3: the session cancellation releases the proctor.
        assert get_proctor_assignment(assignment["id"])["status"] == "RELEASED"
        # Registrations are deliberately untouched by the cascade.
        assert get_registration(registration["id"])["registration_status"] == (
            "REGISTERED"
        )

    def test_clock_advance_before_horizon_triggers_no_cascade(self, api):
        """PRD §3.2: "every authorization record still in `AUTHORIZED` status
        whose `authorized_until` is at or before the new clock reading
        transitions to `EXPIRED` — the boundary is inclusive"
        PRD §2.4: "Every clock advance runs the teacher-authorization expiry
        sweep described in §3.2 before the response is returned"

        Design: Difficulty/transitive_cascade/clock_sweep_expiry_cascade_depth3
        """
        cycle, course, auth, registration, session, assignment = (
            self._build_cascade_scenario(api)
        )
        # One day before authorized_until: the sweep expires nothing.
        set_clock("2028-08-30T00:00:00Z")
        assert get_authorization(auth["id"])["status"] == "AUTHORIZED"
        course = get_course(course["id"])
        assert course["authorized_teacher_count"] == 1
        assert course["status"] == "ACTIVE"
        session = get_session(session["id"])
        assert session["status"] == "SCHEDULED"
        assert session["seats_reserved"] == 1
        assert get_proctor_assignment(assignment["id"])["status"] == "ASSIGNED"
