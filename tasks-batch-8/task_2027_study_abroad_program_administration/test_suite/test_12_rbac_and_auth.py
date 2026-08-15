"""Role-based access control and authentication (PRD §2.1, §2.10)."""
from test_helpers import (
    ApiErrorId,
    create_approved_preapproval,
    create_committed_application,
    create_open_program,
    create_partner_agreement,
    create_pending_preapproval,
    create_program_payload,
    create_student,
    get_statement_for_application,
    make_student_headers,
    setup_open_program_with_application,
    validate_error,
    validate_success,
    api_client,
    COORD_A_HEADERS,
    SAFETY_HEADERS,
)


class TestRoleDenied:
    def test_student_cannot_publish_program(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in the endpoint's
        authorized-role list; an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/student_cannot_publish_program
        """
        agreement = create_partner_agreement()
        program = validate_success(
            api.create_program(create_program_payload(agreement["id"]), COORD_A_HEADERS),
            expected_status=201,
        )
        resp = api.publish_program(
            program["id"], make_student_headers("stu-outsider"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        reread = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert reread["status"] == "DRAFT"

    def test_coordinator_cannot_review_cpa(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in the endpoint's
        authorized-role list; an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/coordinator_cannot_review_cpa
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Rbac Student", "email": "rbac@uni.edu"},
        )
        cpa = create_pending_preapproval(application, student, "HIST310", 3)
        resp = api.review_course_preapproval(
            cpa["id"], {"decision": "APPROVED"}, COORD_A_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_bursar_cannot_create_advisory(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in the endpoint's
        authorized-role list; an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/bursar_cannot_create_advisory
        """
        from test_helpers import BURSAR_HEADERS

        resp = api.create_travel_advisory(
            {
                "country_code": "FR", "level": "CAUTION",
                "effective_from": "2027-01-01T00:00:00Z", "effective_to": "2027-03-01T00:00:00Z",
            },
            BURSAR_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_safety_officer_cannot_record_payment(self, api):
        """PRD §2.1: "Once authenticated, the caller's role must appear in the endpoint's
        authorized-role list; an attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/safety_officer_cannot_record_payment
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Pay Rbac", "email": "payrbac@uni.edu"},
        )
        statement = get_statement_for_application(application["id"])
        resp = api.record_payment(
            statement["id"], {"amount_cents": 1000}, SAFETY_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestOwnershipEnforcement:
    def test_student_cannot_touch_others_application(self, api):
        """PRD §2.1: "This governs every student-scoped interaction — application actions,
        course pre-approval creation and revision, insurance enrollment creation and
        cancellation, incident reporting, and reading one's own student record: whenever the
        linked `student_id` does not equal the caller's `X-User-ID`, the request is rejected
        with `ERR_FORBIDDEN`."

        Design: Corner/rbac/student_cannot_touch_others_application
        """
        program, student_a, app_a = setup_open_program_with_application(
            student_overrides={"full_name": "Owner A", "email": "ownera@uni.edu"},
        )
        student_b = create_student(full_name="Other B", email="otherb@uni.edu", gpa=3.10)

        resp_read = api.get_application(
            app_a["id"], make_student_headers(student_b["id"]),
        )
        validate_error(resp_read, ApiErrorId.ERR_FORBIDDEN)

        resp_withdraw = api.withdraw_application(
            app_a["id"], make_student_headers(student_b["id"]),
        )
        validate_error(resp_withdraw, ApiErrorId.ERR_FORBIDDEN)
        reread = validate_success(api.get_application(app_a["id"], COORD_A_HEADERS))
        assert reread["status"] == "SUBMITTED"


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting an `X-User-Role` value
        outside this list, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_unauthenticated
        """
        agreement = create_partner_agreement()
        resp = api.create_program(
            create_program_payload(agreement["id"], name="No Auth"),
            headers={},  # both headers omitted
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
