"""Difficulty rule cross_entity_state_dependency: confirm gated on the Student
aggregate's state, and offering-open gated on the CredentialApplication
aggregate's state (PRD 3.1, 3.4, 3.5)."""
from test_helpers import (
    ApiErrorId,
    approve_credential,
    begin_review,
    confirm_enrollment_raw,
    create_credential_application,
    get_enrollment,
    get_offering,
    open_offering,
    register_and_confirm,
    register_student,
    setup_base,
    validate_error,
    validate_success,
)


class TestConfirmBlockedByStudentSuspension:
    def test_confirm_under_suspended_student_rejected(self, api, admin_headers):
        """PRD 3.5: "Suspending a student — moving `ELIGIBLE` to `SUSPENDED`,
        invalid in any other state and rejected with `ERR_INVALID_STATE` — does not
        modify existing enrollments but blocks future confirmations with
        `ERR_STUDENT_NOT_ELIGIBLE` (HTTP 409)."
        PRD 3.5: "the student is `ELIGIBLE` and has `grade_level` at least 11 (else
        `ERR_STUDENT_NOT_ELIGIBLE`)"

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_student_suspension
        """
        ctx = setup_base()
        pair = register_student(ctx)
        enrollment_id = pair["enrollment"]["id"]
        suspended = validate_success(api.suspend_student(pair["student"]["id"], admin_headers))
        assert suspended["status"] == "SUSPENDED"

        response = confirm_enrollment_raw(ctx["offering"]["id"], enrollment_id)
        validate_error(response, ApiErrorId.ERR_STUDENT_NOT_ELIGIBLE.value)
        assert get_enrollment(enrollment_id)["status"] == "PENDING_VERIFICATION", (
            "The failed confirm leaves state untouched"
        )
        assert get_offering(ctx["offering"]["id"])["seats_taken"] == 0, (
            "No seat was consumed"
        )

    def test_suspension_does_not_modify_existing_enrollments(self, api, admin_headers):
        """PRD 3.5: "Suspending a student — moving `ELIGIBLE` to `SUSPENDED`,
        invalid in any other state and rejected with `ERR_INVALID_STATE` — does not
        modify existing enrollments but blocks future confirmations with
        `ERR_STUDENT_NOT_ELIGIBLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_student_suspension
        """
        ctx = setup_base()
        pair = register_and_confirm(ctx)
        assert pair["enrollment"]["status"] == "REGISTERED"

        validate_success(api.suspend_student(pair["student"]["id"], admin_headers))
        enrollment_after = get_enrollment(pair["enrollment"]["id"])
        assert enrollment_after["status"] == "REGISTERED", (
            f"Suspension must not modify the existing enrollment, got "
            f"{enrollment_after['status']}"
        )
        offering = get_offering(ctx["offering"]["id"])
        assert offering["seats_taken"] == 1, "The seat stays taken"


class TestOfferingOpenBlockedByCredentialState:
    def test_under_review_application_blocks_open_until_approved(self, api, admin_headers):
        """PRD 3.4: "Opening requires both referenced terms to be `OPEN` (else
        `ERR_TERM_NOT_OPEN`), the course to be `ACTIVE` (else `ERR_INVALID_STATE`),
        and an `APPROVED` `CredentialApplication` to exist matching the offering's
        `instructor_id` and `course_id` (else `ERR_INSTRUCTOR_NOT_CREDENTIALED`,
        HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/offering_open_blocked_by_credential_state
        """
        ctx = setup_base(approve_credential=False, open_offering_flag=False)
        application = create_credential_application(
            ctx["instructor"]["id"], ctx["course"]["id"]
        )
        begin_review(application["id"])  # UNDER_REVIEW is not APPROVED

        response = api.open_offering(ctx["offering"]["id"], admin_headers)
        validate_error(response, ApiErrorId.ERR_INSTRUCTOR_NOT_CREDENTIALED.value)
        assert get_offering(ctx["offering"]["id"])["status"] == "DRAFT", (
            "The failed open leaves the offering DRAFT"
        )

        approve_credential(application["id"])
        opened = open_offering(ctx["offering"]["id"])
        assert opened["status"] == "OPEN", (
            "The exact same request succeeds once the application is APPROVED"
        )

    def test_open_without_any_credential_application_rejected(self, api, admin_headers):
        """PRD 3.4: "Opening requires both referenced terms to be `OPEN` (else
        `ERR_TERM_NOT_OPEN`), the course to be `ACTIVE` (else `ERR_INVALID_STATE`),
        and an `APPROVED` `CredentialApplication` to exist matching the offering's
        `instructor_id` and `course_id` (else `ERR_INSTRUCTOR_NOT_CREDENTIALED`,
        HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/offering_open_blocked_by_credential_state
        """
        ctx = setup_base(approve_credential=False, open_offering_flag=False)
        response = api.open_offering(ctx["offering"]["id"], admin_headers)
        validate_error(response, ApiErrorId.ERR_INSTRUCTOR_NOT_CREDENTIALED.value)
        assert get_offering(ctx["offering"]["id"])["status"] == "DRAFT"
