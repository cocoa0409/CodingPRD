"""Validation-pipeline priority conflicts and cross-entity publish gates.

Covers the fixed precedence ordering of the validation pipeline (PRD §2.6) when
one request violates several rules, and the cross-entity gates on enrollment
and offering publication (PRD §3.4, §3.5).
"""
from test_helpers import (
    ApiErrorId,
    approve_course,
    assert_seat_invariant,
    create_active_course,
    create_credentialed_instructor,
    create_grant,
    create_instructor,
    create_licensed_school,
    create_offering,
    create_published_offering,
    create_proctor,
    create_student,
    enroll,
    enroll_with_seat_time,
    get_enrollment,
    get_offering,
    get_success_data,
    record_attendance,
    setup_publishable_school,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE,
    COMMISSION,
    DIRECTOR,
    REGISTRAR,
    approve_instructor,
)
from test_helpers.fixtures import create_course as _create_course
from test_helpers import api_client


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/seat_time_state_beats_proctor_sod
# ---------------------------------------------------------------------------

class TestSeatTimeStateBeatsProctorSod:
    def _in_progress_enrollment(self, api):
        env = setup_publishable_school()
        _s, enr = enroll(env["offering"]["id"], env["school"]["id"])
        record_attendance(enr["id"], env["instructor"]["id"],
                          session_date="2026-09-03", minutes=60)
        return env, enr

    def test_seat_time_error_wins_over_segregation_error(self, api):
        """PRD §2.6: "rejections follow a fixed precedence, and the first
        matching rule's error is the one returned" — state gates (rule 6,
        `ERR_SEAT_TIME_NOT_MET`) precede regulatory safety (rule 7,
        `ERR_PROCTOR_IS_INSTRUCTOR`).

        Design: Difficulty/priority_pair_validation_conflict/seat_time_state_beats_proctor_sod
        """
        env, enr = self._in_progress_enrollment(api)
        resp = api.create_exam_attempt(
            enr["id"],
            {"scheduled_at": "2026-09-11T14:00:00Z",
             "proctor_instructor_id": env["instructor"]["id"]},
            REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_SEAT_TIME_NOT_MET)

    def test_no_attempt_created_when_both_rules_violated(self, api):
        """PRD §2.6: "6. **State gates.** ... enrollment `SEAT_TIME_MET` for
        attempt creation (`ERR_SEAT_TIME_NOT_MET`) ... 7. **Regulatory safety.**
        ... segregation of duties must hold between proctor and instructor of
        record (`ERR_PROCTOR_IS_INSTRUCTOR`)."

        Design: Difficulty/priority_pair_validation_conflict/seat_time_state_beats_proctor_sod
        """
        env, enr = self._in_progress_enrollment(api)
        resp = api.create_exam_attempt(
            enr["id"],
            {"scheduled_at": "2026-09-11T14:00:00Z",
             "proctor_instructor_id": env["instructor"]["id"]},
            REGISTRAR)
        err = validate_error(resp, ApiErrorId.ERR_SEAT_TIME_NOT_MET)
        assert err["error_id"] != ApiErrorId.ERR_PROCTOR_IS_INSTRUCTOR
        assert get_enrollment(enr["id"])["exam_attempts_used"] == 0


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/offering_update_window_beats_capacity_below_enrolled
# ---------------------------------------------------------------------------

class TestOfferingUpdateWindowBeatsCapacity:
    def _published_with_two(self, api):
        env = setup_publishable_school()
        enroll(env["offering"]["id"], env["school"]["id"])
        enroll(env["offering"]["id"], env["school"]["id"])
        offering = get_offering(env["offering"]["id"])
        return env, offering["version"]

    def test_window_error_wins_over_capacity_error(self, api):
        """PRD §2.6: "rejections follow a fixed precedence, and the first
        matching rule's error is the one returned" — temporal windows (rule 8,
        `ERR_INVALID_OFFERING_WINDOW`) precede capacity limits (rule 10,
        `ERR_CAPACITY_BELOW_ENROLLED`).

        Design: Difficulty/priority_pair_validation_conflict/offering_update_window_beats_capacity_below_enrolled
        """
        env, version = self._published_with_two(api)
        resp = api.update_offering(
            env["offering"]["id"],
            {"start_date": "2026-09-10", "end_date": "2026-09-01", "capacity": 1,
             "expected_offering_version": version},
            DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_OFFERING_WINDOW)

    def test_offering_unchanged_when_both_rules_violated(self, api):
        """PRD §3.4: "The update re-validates the window rules and the instructor
        rest-gap rule against the new dates, and the new capacity may not fall
        below the offering's current `enrolled_count`
        (`ERR_CAPACITY_BELOW_ENROLLED`)." A rejected update changes nothing.

        Design: Difficulty/priority_pair_validation_conflict/offering_update_window_beats_capacity_below_enrolled
        """
        env, version = self._published_with_two(api)
        resp = api.update_offering(
            env["offering"]["id"],
            {"start_date": "2026-09-10", "end_date": "2026-09-01", "capacity": 1,
             "expected_offering_version": version},
            DIRECTOR)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_OFFERING_WINDOW)
        assert err["error_id"] != ApiErrorId.ERR_CAPACITY_BELOW_ENROLLED
        offering = get_offering(env["offering"]["id"])
        assert offering["start_date"] == "2026-09-01"
        assert offering["end_date"] == "2026-09-10"
        assert offering["capacity"] == 2


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/enrollment_requires_offering_published
# ---------------------------------------------------------------------------

class TestEnrollmentRequiresOfferingPublished:
    def test_draft_offering_rejects_enrollment(self, api):
        """PRD §3.5: "Enrollment requires the offering to be `PUBLISHED`
        (`ERR_OFFERING_NOT_OPEN`)".

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_offering_published
        """
        school = create_licensed_school()
        course = create_active_course(school["id"])
        ins = create_credentialed_instructor(school["id"])
        offering = create_offering(course["id"], ins["id"])  # stays DRAFT
        student = create_student(school["id"])
        resp = api.create_enrollment(
            {"offering_id": offering["id"], "student_id": student["id"]}, REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_OFFERING_NOT_OPEN)

    def test_enrollment_succeeds_after_publish(self, api):
        """PRD §3.5: "The new enrollment starts with `academic_status` `ENROLLED`
        and `payment_status` `PENDING`".

        Design: Difficulty/cross_entity_state_dependency/enrollment_requires_offering_published
        """
        school = create_licensed_school()
        course = create_active_course(school["id"])
        ins = create_credentialed_instructor(school["id"])
        offering = create_offering(course["id"], ins["id"])
        get_success_data(api.publish_offering(offering["id"], DIRECTOR))
        student = create_student(school["id"])
        enr = get_success_data(api.create_enrollment(
            {"offering_id": offering["id"], "student_id": student["id"]}, REGISTRAR))
        assert enr["academic_status"] == "ENROLLED"
        assert enr["payment_status"] == "PENDING"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/publish_requires_course_state_authorization
# ---------------------------------------------------------------------------

class TestPublishRequiresCourseStateAuthorization:
    def _nm_offering_without_course_authorization(self, api):
        """Course approved in TX only; instructor approved in TX and NM;
        offering created for NM."""
        school = create_licensed_school()
        course = create_active_course(school["id"])  # TX approval only
        ins = create_credentialed_instructor(school["id"], states=["TX", "NM"])
        offering = create_offering(course["id"], ins["id"], state_code="NM",
                                   delivery_mode="DISTANCE")
        return offering

    def test_publish_rejected_without_state_authorization(self, api):
        """PRD §3.4: "the course must be authorized in the offering's
        `state_code` — either by an `APPROVED` course approval for that state or
        by an `ACTIVE` equivalency grant recognizing the course there, otherwise
        `ERR_COURSE_NOT_AUTHORIZED_IN_STATE`".

        Design: Difficulty/cross_entity_state_dependency/publish_requires_course_state_authorization
        """
        offering = self._nm_offering_without_course_authorization(api)
        resp = api.publish_offering(offering["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_AUTHORIZED_IN_STATE)

    def test_offering_remains_draft_after_rejection(self, api):
        """PRD §3.4: "Publication is the regulatory checkpoint." A rejected
        publish leaves the offering `DRAFT` ("A new offering stands `DRAFT`").

        Design: Difficulty/cross_entity_state_dependency/publish_requires_course_state_authorization
        """
        offering = self._nm_offering_without_course_authorization(api)
        resp = api.publish_offering(offering["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_AUTHORIZED_IN_STATE)
        assert get_offering(offering["id"])["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/publish_via_equivalency_grant_but_instructor_not_approved
# ---------------------------------------------------------------------------

class TestPublishViaGrantButInstructorNotApproved:
    def _nm_offering_with_grant(self, api):
        """Course TX-approved and ACTIVE; ACTIVE grant TX->NM; instructor TX-only;
        NM offering."""
        school = create_licensed_school()
        course = create_active_course(school["id"])
        create_grant(course["id"], "TX", "NM", course["version"])
        ins = create_credentialed_instructor(school["id"])  # TX only
        offering = create_offering(course["id"], ins["id"], state_code="NM",
                                   delivery_mode="DISTANCE")
        return school, ins, offering

    def test_instructor_leg_fails_after_course_leg_satisfied_by_grant(self, api):
        """PRD §3.4: "the course must be authorized in the offering's
        `state_code` — either by an `APPROVED` course approval for that state or
        by an `ACTIVE` equivalency grant recognizing the course there... — and
        the instructor must hold an `APPROVED` instructor approval in that state,
        otherwise `ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE`."

        Design: Difficulty/cross_entity_state_dependency/publish_via_equivalency_grant_but_instructor_not_approved
        """
        _school, _ins, offering = self._nm_offering_with_grant(api)
        resp = api.publish_offering(offering["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE)

    def test_publish_succeeds_once_instructor_approved(self, api):
        """PRD §3.4: "Publishing a `DRAFT` offering enforces five gates... and
        the instructor must hold an `APPROVED` instructor approval in that state,
        otherwise `ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE`. A published offering
        opens for enrollment." Grant-based authorization is accepted once both
        legs pass.

        Design: Difficulty/cross_entity_state_dependency/publish_via_equivalency_grant_but_instructor_not_approved
        """
        _school, ins, offering = self._nm_offering_with_grant(api)
        resp = api.publish_offering(offering["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_APPROVED_IN_STATE)
        approve_instructor(ins["id"], state_code="NM")
        published = get_success_data(api.publish_offering(offering["id"], DIRECTOR))
        assert published["status"] == "PUBLISHED"
