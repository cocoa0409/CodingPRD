"""Authentication, authorization, and left-to-right existence checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_manual_dose,
    api_client,
    create_outbreak_event_payload,
    create_student,
    rescind_notice_payload,
    submit_exemption,
    validate_error,
)


class TestAuthentication:

    def test_missing_auth_header_returns_unauthenticated(self):
        """PRD section 2.1: "Every request to the API must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
        operational capacity in which they act."
        PRD section 2.1: "A request missing either header, or presenting an
        `X-User-Role` value that is not one of these four declared roles, is
        rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        # X-User-ID present, X-User-Role absent.
        resp = api_client.list_students(
            {"X-User-ID": "clerk-1", "Content-Type": "application/json"}
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:

    def test_clerk_cannot_approve_exemption_returns_forbidden(self, clerk_headers):
        """PRD section 2.1: "A request whose role is authenticated but not among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN`."
        PRD section 3.4: "Adjudication is reserved for a `DistrictHealthOfficer`,
        with a hard segregation rule: the reviewing officer must not be the person
        who submitted the request."

        Design: Corner/rbac/clerk_cannot_approve_exemption_returns_forbidden
        """
        student = create_student("SCH-RB", legal_name="Rbac One")
        exemption = submit_exemption(student["id"], document_ref="doc://rb-1")
        resp = api_client.approve_exemption(exemption["id"], clerk_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_nurse_cannot_declare_outbreak_returns_forbidden(self, nurse_headers):
        """PRD section 2.1: "A request whose role is authenticated but not among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN`."
        PRD section 3.6: "When a vaccine-preventable disease appears in a school, a
        `DistrictHealthOfficer` declares an OutbreakEvent for the affected
        `school_code` and `vaccine_code`."

        Design: Corner/rbac/nurse_cannot_declare_outbreak_returns_forbidden
        """
        resp = api_client.create_outbreak_event(
            create_outbreak_event_payload(school_code="SCH-RB"), nurse_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_coordinator_cannot_verify_dose_returns_forbidden(
        self, coordinator_headers
    ):
        """PRD section 2.1: "A request whose role is authenticated but not among
        the roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN`."
        PRD section 3.3: "Verification belongs to the `SchoolNurse`."

        Design: Corner/rbac/coordinator_cannot_verify_dose_returns_forbidden
        """
        student = create_student("SCH-RB", legal_name="Rbac Two")
        record = add_manual_dose(student["id"], student["version"])
        assert record["status"] == "PENDING_VERIFICATION"
        resp = api_client.verify_immunization_record(
            record["id"], coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestExistenceChecks:
    """PRD section 2.7: "3. **Existence** — path-template identifiers are resolved
    left to right, and then body foreign-key identifiers (such as `student_id`) are
    resolved; an unresolvable identifier yields the corresponding not-found error:
    `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`, `ERR_EXEMPTION_NOT_FOUND`,
    `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_SNAPSHOT_NOT_FOUND`."
    """

    def test_verify_unknown_record_returns_404(self, nurse_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/verify_unknown_record_returns_404
        """
        resp = api_client.verify_immunization_record(NON_EXISTENT_UUID, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_RECORD_NOT_FOUND)

    def test_rescind_unknown_notice_returns_404(self, officer_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/rescind_unknown_notice_returns_404
        """
        resp = api_client.rescind_notice(
            NON_EXISTENT_UUID, rescind_notice_payload(reason="no such notice"),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_NOT_FOUND)

    def test_lift_unknown_outbreak_returns_404(self, officer_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/lift_unknown_outbreak_returns_404
        """
        resp = api_client.lift_outbreak_event(NON_EXISTENT_UUID, officer_headers)
        validate_error(resp, ApiErrorId.ERR_OUTBREAK_NOT_FOUND)

    def test_open_unknown_session_returns_404(self, nurse_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/open_unknown_session_returns_404
        """
        resp = api_client.open_clinic_session(NON_EXISTENT_UUID, nurse_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_FOUND)

    def test_cancel_unknown_appointment_returns_404(self, clerk_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/cancel_unknown_appointment_returns_404
        """
        resp = api_client.cancel_appointment(NON_EXISTENT_UUID, clerk_headers)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND)

    def test_finalize_unknown_snapshot_returns_404(self, officer_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/finalize_unknown_snapshot_returns_404
        """
        resp = api_client.finalize_compliance_snapshot(
            NON_EXISTENT_UUID, officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_SNAPSHOT_NOT_FOUND)

    def test_start_review_unknown_exemption_returns_404(self, officer_headers):
        """PRD section 2.7: "an unresolvable identifier yields the corresponding
        not-found error: `ERR_STUDENT_NOT_FOUND`, `ERR_RECORD_NOT_FOUND`,
        `ERR_EXEMPTION_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or
        `ERR_SNAPSHOT_NOT_FOUND`."

        Design: Corner/errors/start_review_unknown_exemption_returns_404
        """
        resp = api_client.start_exemption_review(NON_EXISTENT_UUID, officer_headers)
        validate_error(resp, ApiErrorId.ERR_EXEMPTION_NOT_FOUND)
