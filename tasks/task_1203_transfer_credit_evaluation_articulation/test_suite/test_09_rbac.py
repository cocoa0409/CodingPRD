"""Role-based access control: exclusive write surfaces and shared reads."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_student_headers,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]


class TestStudentRoleCannotCreateAgreement:
    def test_student_role_cannot_create_agreement_forbidden(self):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /api/articulation-agreements is authorized for
        RegistrarAdmin only.

        Design: Corner/rbac/student_role_cannot_create_agreement_forbidden
        """
        partner = fixtures.create_partner(name="Role College", code="RO")
        student = fixtures.create_student(major="MATH")

        resp = api_client.create_articulation_agreement(
            {
                "partner_institution_id": partner["id"],
                "program_scope": "ALL",
                "effective_start": "2024-08-01",
                "effective_end": "2027-07-31",
            },
            make_student_headers(student["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestEvaluatorCannotVerifyTranscript:
    def test_evaluator_cannot_verify_transcript_forbidden(self):
        """PRD §2.1: "`TransferCenterStaff` — intake staff; receives, verifies,
        and rejects transcripts."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/evaluator_cannot_verify_transcript_forbidden
        """
        partner = fixtures.create_partner(name="Role College", code="RO")
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_transcript(student["id"], partner["id"], courses=[])

        resp = api_client.verify_transcript(transcript["id"], EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        stored = get_success_data(api_client.get_transcript(transcript["id"], STAFF))
        assert stored["status"] == "RECEIVED"


class TestAdminCannotStartPetitionReview:
    def test_admin_cannot_start_petition_review_forbidden(self):
        """PRD §2.1: "`FacultyAdjudicator` — faculty reviewer for syllabus
        petitions and appeals."
        PRD §2.1: "A request whose role is not permitted on the target endpoint
        is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/admin_cannot_start_petition_review_forbidden
        """
        ctx = fixtures.setup_petition_required_line()
        petition = fixtures.file_petition(
            ctx["line"]["id"], ctx["course"]["id"], ctx["student"]["id"],
            syllabus_ref="s3://syllabi/v1.pdf",
        )

        resp = api_client.start_petition_review(petition["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        stored = get_success_data(api_client.get_petition(petition["id"], EVALUATOR))
        assert stored["status"] == "SUBMITTED"


class TestStudentReadsOwnRecord:
    def test_student_reads_own_record_allowed(self):
        """PRD §2.1: "When `X-User-Role` is `Student`, `X-User-ID` is the `id` of
        the acting `TransferStudent`" — and §4 authorizes GET /api/students/{id}
        for any role.

        Design: Corner/rbac/student_reads_own_record_allowed
        """
        student = fixtures.create_student(major="MATH")

        resp = api_client.get_student(student["id"], make_student_headers(student["id"]))
        data = validate_success(resp)
        assert data["full_name"] == student["full_name"]
