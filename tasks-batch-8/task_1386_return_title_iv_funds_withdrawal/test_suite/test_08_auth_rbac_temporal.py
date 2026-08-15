"""Authentication headers, role authorization, student ownership, and
temporal validations."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_student,
    get_enrollment,
    setup_pell_only_case,
    setup_pwd_case,
    setup_term_student_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_official,
)
from test_helpers.test_users import make_student_headers

REGISTRAR = TEST_USERS["registrar_clerk_headers"]
OFFICER = TEST_USERS["financial_aid_officer_headers"]
BURSAR = TEST_USERS["bursar_clerk_headers"]


class TestAuthContext:

    def test_request_missing_auth_header_rejected(self):
        """PRD section 2.1: "Each request must include `X-User-ID` to
        identify the acting user and `X-User-Role` to specify their
        operational capacity."
        PRD section 2.1: "A request missing either header, or carrying a
        role value outside this declared set, is rejected with an
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error."

        Design: Corner/validations/request_missing_auth_header_rejected
        """
        resp = api_client.create_term(
            {"name": "NoAuth", "start_date": "2026-08-24",
             "end_date": "2026-12-11"},
            headers={})
        validate_error(
            resp, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            expected_status=400)


class TestRoleAuthorization:

    def test_student_cannot_create_term(self):
        """PRD section 2.1: "Access to specific operations is further
        restricted by role: an attempt to perform an action outside the
        caller's designated role is rejected with an `ERR_FORBIDDEN_FOR_ROLE`
        error."
        PRD section 2.1: "a `RegistrarClerk` owns terms, breaks, students,
        enrollments, withdrawal initiation and rescission, and enrollment
        completion."

        Design: Corner/validations/student_cannot_create_term
        """
        resp = api_client.create_term(
            {"name": "StuTerm", "start_date": "2026-08-24",
             "end_date": "2026-12-11"},
            make_student_headers("00000000-0000-4000-8000-0000000000aa"))
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)

    def test_registrar_cannot_record_return(self):
        """PRD section 2.1: "Access to specific operations is further
        restricted by role: an attempt to perform an action outside the
        caller's designated role is rejected with an `ERR_FORBIDDEN_FOR_ROLE`
        error."
        PRD section 3.6: "Recording a return is shared between the
        `BursarClerk` and the `FinancialAidOfficer`"

        Design: Corner/rbac/registrar_cannot_record_return
        """
        scen = setup_pell_only_case()
        ob = scen["obligations"][0]
        resp = api_client.record_return(ob["id"], {"amount_cents": 80_000},
                                        REGISTRAR)
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


class TestStudentWithdrawalPathway:

    def test_student_unofficial_withdraw_forbidden(self):
        """PRD section 3.4: "Two restrictions apply to the student pathway:
        the caller's identity must match the enrollment's `student_id`
        (otherwise `ERR_OWNERSHIP_MISMATCH`), and a student may report only
        an official withdrawal — an `UNOFFICIAL` request from a `Student` is
        rejected with `ERR_FORBIDDEN_FOR_ROLE`."

        Design: Corner/validations/student_unofficial_withdraw_forbidden
        """
        _, student, enrollment = setup_term_student_enrollment(
            charges=600_000)
        resp = api_client.withdraw_enrollment(
            enrollment["id"], {"withdrawal_type": "UNOFFICIAL"},
            make_student_headers(student["id"]))
        validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)

    def test_student_can_withdraw_own_enrollment_official(self):
        """PRD section 3.4: "A withdrawal begins when a `RegistrarClerk` —
        or the student themselves — initiates it against an `ENROLLED`
        enrollment with a payload naming the `withdrawal_type`, either
        `OFFICIAL` or `UNOFFICIAL`."
        PRD section 3.4: "For an official withdrawal, the `withdrawal_date`
        is the supplied `notification_date`, and the `determination_date`
        equals it."

        Design: Corner/rbac/student_can_withdraw_own_enrollment_official
        """
        _, student, enrollment = setup_term_student_enrollment(
            charges=600_000)
        resp = api_client.withdraw_enrollment(
            enrollment["id"],
            {"withdrawal_type": "OFFICIAL", "notification_date": "2026-10-25"},
            make_student_headers(student["id"]))
        case = validate_success(resp, 201)
        assert case["status"] == "OPEN"
        assert case["withdrawal_date"] == "2026-10-25"
        assert case["determination_date"] == "2026-10-25"
        assert get_enrollment(enrollment["id"])["status"] == "WITHDRAWN"

    def test_student_cannot_respond_to_other_students_offer(self):
        """PRD section 3.6: "Responding to an offer is the student's own
        action: the caller's identity must match the owning enrollment's
        `student_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and the offer must
        still be `SENT`"
        PRD section 2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the
        `id` of the acting `Student`; ownership checks on any resource that
        references a `Student` compare the resource's student reference to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_OWNERSHIP_MISMATCH`."

        Design: Corner/validations/student_cannot_respond_to_other_students_offer
        """
        scen = setup_pwd_case(charges=500_000, clock="2026-10-26T09:00:00Z")
        offer = scen["offers"][0]
        other_student = create_student()
        resp = api_client.accept_offer(
            offer["id"], make_student_headers(other_student["id"]))
        validate_error(resp, "ERR_OWNERSHIP_MISMATCH", expected_status=403)
        after = validate_success(api_client.get_post_withdrawal_offer(
            offer["id"], OFFICER), 200)
        assert after["status"] == "SENT"


class TestTemporalValidations:

    def test_notification_date_out_of_period_rejected(self):
        """PRD section 3.4: "Every supplied date must lie inside the period
        from the term's `start_date` through its `end_date` inclusive; a date
        outside that range is rejected with `ERR_DATE_OUT_OF_PERIOD`."

        Design: Corner/validations/notification_date_out_of_period_rejected
        """
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        resp = api_client.withdraw_enrollment(
            enrollment["id"],
            {"withdrawal_type": "OFFICIAL", "notification_date": "2026-08-01"},
            REGISTRAR)
        validate_error(resp, "ERR_DATE_OUT_OF_PERIOD", expected_status=422)
        assert get_enrollment(enrollment["id"])["status"] == "ENROLLED"

    def test_attendance_date_required_rejected(self):
        """PRD section 3.4: "An `UNOFFICIAL` withdrawal on a term whose
        `attendance_taking_required` is true must carry a
        `last_attendance_date`, the documented last date of attendance, and
        its absence is rejected with `ERR_ATTENDANCE_DATE_REQUIRED`."

        Design: Corner/validations/attendance_date_required_rejected
        """
        _, _, enrollment = setup_term_student_enrollment(
            charges=600_000,
            term_overrides={"name": "Fall Att",
                            "attendance_taking_required": True})
        resp = api_client.withdraw_enrollment(
            enrollment["id"], {"withdrawal_type": "UNOFFICIAL"}, REGISTRAR)
        validate_error(resp, "ERR_ATTENDANCE_DATE_REQUIRED",
                       expected_status=422)
        enr = get_enrollment(enrollment["id"])
        assert enr["status"] == "ENROLLED"
        assert enr["current_withdrawal_case_id"] is None

    def test_complete_before_term_end_rejected(self):
        """PRD section 3.2: "Completion is permitted only from `ENROLLED` —
        any other status yields `ERR_INVALID_STATE` — and only once the
        current logical date is strictly later than the term's `end_date`, or
        the request fails with `ERR_TERM_NOT_ENDED`."
        PRD section 2.5: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it advances only when an operator
        explicitly moves it."

        Design: Corner/validations/complete_before_term_end_rejected
        """
        # The logical clock is untouched: 2026-08-01, before the term's
        # end_date 2026-12-11.
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        resp = api_client.complete_enrollment(enrollment["id"], REGISTRAR)
        validate_error(resp, "ERR_TERM_NOT_ENDED", expected_status=409)
        assert get_enrollment(enrollment["id"])["status"] == "ENROLLED"


class TestDoubleWithdrawPriority:

    def _setup_withdrawn(self):
        _, _, enrollment = setup_term_student_enrollment(charges=600_000)
        case = withdraw_official(enrollment["id"], "2026-09-02")
        return enrollment, case

    def test_already_withdrawn_masks_out_of_period_date(self):
        """PRD section 3.4: "Acting on an enrollment already `WITHDRAWN` is
        rejected with `ERR_ENROLLMENT_ALREADY_WITHDRAWN`, and on a
        `COMPLETED` one with `ERR_INVALID_STATE`."
        PRD section 2.9: "When several checks could reject the same request,
        the server evaluates them in a fixed priority order and surfaces the
        earliest applicable failure rather than an arbitrary one"
        (state validity is priority 6; temporal rules are priority 8).

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_double_withdraw
        """
        enrollment, case = self._setup_withdrawn()
        # The date 2027-01-15 is also outside the term — but the state
        # failure at priority 6 must surface first.
        resp = api_client.withdraw_enrollment(
            enrollment["id"],
            {"withdrawal_type": "OFFICIAL", "notification_date": "2027-01-15"},
            REGISTRAR)
        validate_error(resp, "ERR_ENROLLMENT_ALREADY_WITHDRAWN",
                       expected_status=409)
        # No second case was created.
        data, meta = validate_paginated(api_client.list_withdrawal_cases(
            REGISTRAR, params={"enrollment_id": enrollment["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == case["id"]

    def test_already_withdrawn_rejected_even_with_valid_date(self):
        """PRD section 3.4: "Acting on an enrollment already `WITHDRAWN` is
        rejected with `ERR_ENROLLMENT_ALREADY_WITHDRAWN`, and on a
        `COMPLETED` one with `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_double_withdraw
        """
        enrollment, case = self._setup_withdrawn()
        resp = api_client.withdraw_enrollment(
            enrollment["id"],
            {"withdrawal_type": "OFFICIAL", "notification_date": "2026-09-10"},
            REGISTRAR)
        validate_error(resp, "ERR_ENROLLMENT_ALREADY_WITHDRAWN",
                       expected_status=409)
        assert get_enrollment(enrollment["id"])["status"] == "WITHDRAWN"
