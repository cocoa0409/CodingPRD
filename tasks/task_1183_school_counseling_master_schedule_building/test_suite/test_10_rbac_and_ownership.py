"""Role-based access control and ownership checks."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_counselor_headers, make_student_headers,
    setup_counselor, setup_term, setup_course, setup_student,
    make_and_submit_request, drive_term_to_building, list_term_sections,
    get_term_version,
)

ADMIN = TEST_USERS["admin_headers"]


class TestRoleDenial:
    def test_rbac_student_cannot_publish(self, api):
        """PRD §2.1: "A request whose role is not among the roles permitted for
        the target endpoint (see §4) is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: `POST /scheduling/terms/{id}/publish` is authorized for
        Administrator only.

        Design: Corner/validations/rbac_student_cannot_publish
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Rb")
        term = setup_term("2052-FALL")
        student = setup_student(counselor["id"], "RB01", grade_level=9)
        resp = api.publish_term(term["id"], make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

    def test_counselor_cannot_schedule_sections(self, api):
        """PRD §2.1: "A request whose role is not among the roles permitted for
        the target endpoint (see §4) is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: `PATCH /scheduling/sections/{id}` is authorized for
        Administrator only.

        Design: Corner/rbac/counselor_cannot_schedule_sections
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Deny")
        term = setup_term("2068-FALL")
        course = setup_course("DNY-1", credits=1.0, subject_area="ELECTIVE")
        student = setup_student(counselor["id"], "DNY1", grade_level=9)
        make_and_submit_request(student["id"], course["id"], term["id"], 1)
        drive_term_to_building(term["id"])
        section = list_term_sections(term["id"])[0]
        resp = api.patch_section(section["id"], {
            "teacher_id": NON_EXISTENT_UUID, "room_id": NON_EXISTENT_UUID,
            "period": 1, "capacity": 32,
            "expected_term_version": get_term_version(term["id"]),
        }, make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestExistencePrecedence:
    def test_existence_beats_state_on_missing_resource(self, api):
        """PRD §2.8: "the request fails with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not resolve to an existing resource."
        PRD §2.8: "Authentication (`ERR_UNAUTHENTICATED`) precedes role
        authorization (`ERR_UNAUTHORIZED`), which precedes the existence checks
        above. Once everything exists, the term-posture gate fires ... then
        from-state legality on the target entity (`ERR_INVALID_STATE`, HTTP 409)"

        Design: Corner/validations/existence_beats_state_on_missing_resource
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Ex")
        resp = api.claim_change_request(
            NON_EXISTENT_UUID, make_counselor_headers(counselor["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestStudentScheduleOwnership:
    def test_student_reads_own_schedule_only(self, api):
        """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id`
        of the acting `Student`; ownership checks on any resource that
        references a student compare the resource's `student_id` to
        `X-User-ID`."
        PRD §3.5: "A student's schedule for a term — their schedule entries in
        any state — is readable throughout" — their own, not another student's.

        Design: Corner/rbac/student_reads_own_schedule_only
        """
        counselor = setup_counselor(max_caseload=50, full_name="C Xy")
        s_x = setup_student(counselor["id"], "XX01", grade_level=9)
        s_y = setup_student(counselor["id"], "YY01", grade_level=9)
        term = setup_term("2070-FALL")
        resp = api.get_student_schedule(
            s_y["id"], make_student_headers(s_x["id"]), params={"term_id": term["id"]})
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)
        own = api.get_student_schedule(
            s_x["id"], make_student_headers(s_x["id"]), params={"term_id": term["id"]})
        data = validate_success(own, 200)
        assert data == []
