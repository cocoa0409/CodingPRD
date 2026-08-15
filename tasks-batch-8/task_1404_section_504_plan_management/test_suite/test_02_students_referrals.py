"""Student addressing and the referral intake state machine (PRD §2.6, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_school,
    create_staff,
    create_student_for,
    make_coordinator_headers,
    make_teacher_headers,
    submit_referral,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestStudentAddressing:
    def test_student_get_non_existent_returns_404(self, api):
        """PRD §2.6: "Whenever a path-templated identifier or a referenced body
        identifier does not correspond to an existing resource, the request is
        rejected with HTTP 404: the generic `ERR_NOT_FOUND`, or the
        resource-specific `ERR_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`,
        `ERR_STAFF_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_ACCOMMODATION_NOT_FOUND`, `ERR_ACK_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND`, `ERR_TESTING_REQUEST_NOT_FOUND`,
        `ERR_GRIEVANCE_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`, or
        `ERR_CONSENT_RECORD_NOT_FOUND`."

        Design: Corner/entities/student_get_non_existent_returns_404
        """
        from test_helpers import TEST_USERS
        resp = api.get_student(NON_EXISTENT_UUID, TEST_USERS["director_headers"])
        # PRD permits either the generic or the resource-specific 404 id.
        assert resp.status_code == 404, f"missing student must yield 404, got {resp.status_code}"
        err = validate_error_is_one_of(resp, [ApiErrorId.ERR_NOT_FOUND, ApiErrorId.ERR_STUDENT_NOT_FOUND])
        assert err in (ApiErrorId.ERR_NOT_FOUND, ApiErrorId.ERR_STUDENT_NOT_FOUND)

    def test_referral_fk_student_must_exist(self, api):
        """PRD §2.6: "Whenever a path-templated identifier or a referenced body
        identifier does not correspond to an existing resource, the request is
        rejected with HTTP 404: the generic `ERR_NOT_FOUND`, or the
        resource-specific `ERR_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`,
        `ERR_STAFF_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
        `ERR_EVALUATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`,
        `ERR_ACCOMMODATION_NOT_FOUND`, `ERR_ACK_NOT_FOUND`,
        `ERR_REVIEW_NOT_FOUND`, `ERR_TESTING_REQUEST_NOT_FOUND`,
        `ERR_GRIEVANCE_NOT_FOUND`, `ERR_TRAINING_RECORD_NOT_FOUND`, or
        `ERR_CONSENT_RECORD_NOT_FOUND`."

        Design: Corner/entities/referral_fk_student_must_exist
        """
        resp = api.create_referral(
            {"student_id": NON_EXISTENT_UUID, "referral_reason": "r",
             "suspected_disability_category": "LEARNING"},
            make_teacher_headers("some-teacher"),
        )
        assert resp.status_code == 404, f"referral against a missing student must yield 404, got {resp.status_code}"
        err = validate_error_is_one_of(resp, [ApiErrorId.ERR_NOT_FOUND, ApiErrorId.ERR_STUDENT_NOT_FOUND])
        assert err in (ApiErrorId.ERR_NOT_FOUND, ApiErrorId.ERR_STUDENT_NOT_FOUND)


class TestReferralStateMachine:
    def _setup_referral(self, api):
        school = create_school()
        co = create_staff(school["id"], "COORDINATOR")
        student = create_student_for(school["id"], co["id"])
        return school, co, student

    def test_referral_starts_in_pending(self, api):
        """PRD §3.2: "On acceptance the referral is stamped `submitted_at` from
        the logical clock, its `review_deadline` is computed as fifteen calendar
        days after `submitted_at` (driving overdue tracking on the referral
        queue), the submitter's identity is recorded in `submitted_by_staff_id`
        from `X-User-ID`, the referral enters `PENDING`, the student moves `NONE`
        → `REFERRED`, and a `REFERRAL_SUBMITTED` audit event is appended."

        Design: Corner/state_machines/referral_starts_in_pending
        """
        school, co, student = self._setup_referral(api)
        resp = api.create_referral(
            {"student_id": student["id"], "referral_reason": "r",
             "suspected_disability_category": "LEARNING"},
            make_coordinator_headers(co["id"]),
        )
        referral = validate_success(resp, expected_status=201)
        assert referral["referral_status"] == "PENDING", (
            f"a newly created referral must enter PENDING, got {referral['referral_status']}"
        )

    def test_referral_start_review_twice_rejected(self, api):
        """PRD §3.2: "Starting review requires the referral to be `PENDING`
        (otherwise `ERR_REFERRAL_NOT_PENDING`), the student to be in `REFERRED`
        (otherwise `ERR_STUDENT_NOT_IN_REFERRED_STATE`), and the school's posture
        to be anything but `AUDIT_HOLD` (otherwise `ERR_SCHOOL_UNDER_AUDIT_HOLD`);
        it moves the referral `PENDING` → `UNDER_REVIEW` and emits
        `REFERRAL_REVIEWED`."

        Design: Corner/state_machines/referral_start_review_twice_rejected
        """
        school, co, student = self._setup_referral(api)
        referral = submit_referral(student["id"], co["id"], role="Section504Coordinator")
        first = api.start_referral_review(referral["id"], make_coordinator_headers(co["id"]))
        validate_success(first)
        second = api.start_referral_review(referral["id"], make_coordinator_headers(co["id"]))
        validate_error(second, ApiErrorId.ERR_REFERRAL_NOT_PENDING)

    def test_referral_terminal_state_lockdown_rejected(self, api):
        """PRD §3.2: "Withdrawing is permitted from either `PENDING` or
        `UNDER_REVIEW` (otherwise `ERR_REFERRAL_NOT_WITHDRAWABLE`), moves the
        referral to `WITHDRAWN`, and likewise returns the student `REFERRED` →
        `NONE`."

        Design: Corner/state_machines/referral_terminal_state_lockdown_rejected
        """
        school, co, student = self._setup_referral(api)
        referral = submit_referral(student["id"], co["id"], role="Section504Coordinator")
        validate_success(api.start_referral_review(referral["id"], make_coordinator_headers(co["id"])))
        validate_success(api.reject_referral(referral["id"], make_coordinator_headers(co["id"])))
        resp = api.withdraw_referral(referral["id"], make_coordinator_headers(co["id"]))
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_WITHDRAWABLE)

    def test_err_referral_not_under_review_on_initiate(self, api):
        """PRD §3.2: "Initiating an evaluation moves the referral `UNDER_REVIEW`
        → `EVALUATION_INITIATED`, creates a new EligibilityEvaluation in
        `INITIATED` linked back through `referral_id`, moves the student
        `REFERRED` → `EVALUATING`, and emits `EVALUATION_INITIATED`; it is
        rejected with `ERR_REFERRAL_NOT_UNDER_REVIEW` if the referral is not
        under review, and with `ERR_EVALUATION_ALREADY_OPEN` if the student
        already has any evaluation in a non-terminal state."

        Design: Corner/errors/err_referral_not_under_review_on_initiate
        """
        school, co, student = self._setup_referral(api)
        referral = submit_referral(student["id"], co["id"], role="Section504Coordinator")
        # Referral is still PENDING — start-review was never called.
        resp = api.initiate_evaluation(referral["id"], {}, make_coordinator_headers(co["id"]))
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_UNDER_REVIEW)
