"""Authentication, authorization, and role portfolios."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_district,
    create_enrolled_student,
    create_service_delivery_payload,
    create_special_ed_enrolled_student,
    create_stipend,
    create_teacher,
    create_teacher_assignment_payload,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
ACADEMIC = TEST_USERS["academic_director_headers"]
PROCTOR = TEST_USERS["proctor_coordinator_headers"]
SPECIAL_ED = TEST_USERS["special_ed_coordinator_headers"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, carrying an empty
        `X-User-ID`, or naming a role outside the six above is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.list_students({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestAuthorization:
    def test_wrong_role_cannot_withdraw_student(self, api):
        """PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: "| POST | `/vks/students/{id}/withdraw` | Withdraw a student,
        cascading stipends, assignments, bookings, and sessions, and compute
        funding proration | EnrollmentOfficer |"

        Design: Corner/validations/wrong_role_unauthorized
        """
        _, student = create_enrolled_student(
            district=create_district(district_code="D-130", state_code="CA",
                                     funding_rate_cents=500, enrollment_cap=50))
        resp = api.withdraw_student(student["id"], "DROPOUT", FINANCE)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_academic_director_cannot_issue_stipends(self, api):
        """PRD §2.1: "A `FinanceOfficer` issues device and internet stipends
        and processes their returns; it cannot enroll students or manage
        teachers."
        PRD §4: "| POST | `/vks/stipends/{id}/issue` | Issue a REQUESTED
        stipend | FinanceOfficer |"
        PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/academic_director_cannot_issue_stipends
        """
        _, student = create_enrolled_student(
            district=create_district(district_code="D-160", state_code="CA",
                                     funding_rate_cents=500, enrollment_cap=50))
        stipend = create_stipend(student["id"], stipend_type="DEVICE",
                                 amount_cents=10000)
        resp = api.issue_stipend(stipend["id"], ACADEMIC)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_enrollment_officer_cannot_manage_teacher_assignments(self, api):
        """PRD §2.1: "An `AcademicDirector` registers teachers and manages
        teacher-to-student assignments; it cannot touch stipends or
        proctoring."
        PRD §4: "| POST | `/vks/teacher-assignments` | Assign a teacher to a
        student for a subject | AcademicDirector |"
        PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/enrollment_officer_cannot_manage_teachers
        """
        district = create_district(district_code="D-161", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        _, student = create_enrolled_student(district=district, legal_name="R2")
        teacher = create_teacher(full_name="T", certification_state_codes=["CA"],
                                 caseload_cap=30)
        resp = api.create_teacher_assignment(
            create_teacher_assignment_payload(teacher["id"], student["id"],
                                              subject="MATH"),
            ENROLLMENT,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_proctor_coordinator_cannot_manage_service_deliveries(self, api):
        """PRD §2.1: "A `SpecialEdCoordinator` schedules, delivers, marks
        missed, cancels, and reschedules special-education service sessions."
        PRD §4: "| POST | `/vks/service-deliveries` | Schedule an online
        special-education service session | SpecialEdCoordinator |"
        PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/proctor_coordinator_cannot_manage_service_deliveries
        """
        district = create_district(district_code="D-162", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        _, student = create_special_ed_enrolled_student(district=district,
                                                        legal_name="R3")
        provider = create_teacher(full_name="T", certification_state_codes=["CA"],
                                  caseload_cap=30)
        resp = api.create_service_delivery(
            create_service_delivery_payload(
                student["id"], provider["id"], service_type="COUNSELING",
                scheduled_at="2026-08-10T10:00:00Z", duration_minutes=30),
            PROCTOR,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_special_ed_coordinator_cannot_set_clock(self, api):
        """PRD §2.1: "A `PlatformAdmin` holds the superset of permissions: it
        alone manages districts and the logical clock, and it shares in
        several registration and read operations."
        PRD §4: "| POST | `/vks/_clock/set_current_utc` | Set the server's
        logical clock and fire pending time-driven transitions |
        PlatformAdmin |"
        PRD §2.1: "A request whose role is authenticated but is not in the
        endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."

        Design: Corner/rbac/special_ed_coordinator_cannot_set_clock
        """
        resp = api.set_clock("2026-08-05T00:00:00Z", SPECIAL_ED)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
