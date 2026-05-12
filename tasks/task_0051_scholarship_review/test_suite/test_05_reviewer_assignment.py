"""Reviewer-pool management + assign-reviewers + COI checks."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assign_reviewers_payload,
    assign_three_reviewers,
    close_and_review,
    create_open_scholarship,
    create_reviewer,
    create_reviewer_set,
    create_submitted_application,
    dept_review_pass,
    new_student_id,
    validate_error,
    validate_success,
)


def _build_pass_state(*, student_dept="STU-DEPT", reviewer_dept="REV-DEPT",
                     advisor_id=None, family_relation=None):
    """Common helper: open scholarship + submitted app + dept-pass.
    Returns (sch, app)."""
    sch, _ = create_open_scholarship(
        category="MERIT",
        required_materials=["TRANSCRIPT"],
        department_code=student_dept,
        gpa_threshold_x100=0,
    )
    sid = new_student_id()
    app, _ = create_submitted_application(
        sch, student_id=sid,
        student_department_code=student_dept,
        uploaded_materials=["TRANSCRIPT"],
        student_advisor_id=advisor_id,
    )
    close_and_review(sch)
    dept_review_pass(
        sch["id"], app["id"],
        dept_code=student_dept,
        uploaded_materials=["TRANSCRIPT"],
    )
    return sch, app, sid


class TestAssignReviewerCount:

    def test_assign_with_wrong_count_rejected(self):
        """PRD §3.5: "A SchoolAdmin calls the assign-reviewers capability
        with a payload reviewer_ids containing exactly three reviewer ids;
        any other cardinality yields ERR_REVIEWER_COUNT_INVALID."

        Claim: 2 reviewer_ids -> ERR_REVIEWER_COUNT_INVALID.
        """
        sch, app, _ = _build_pass_state()
        reviewers = create_reviewer_set(2, department_code="REV-DEPT")
        resp = api_client.assign_reviewers(
            sch["id"], app["id"],
            assign_reviewers_payload(
                reviewer_ids=[r["id"] for r in reviewers],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_COUNT_INVALID.value)

    def test_assign_with_duplicate_reviewer_ids_rejected(self):
        """PRD §3.5: "The three ids must be distinct from each other;
        duplicates yield ERR_REVIEWER_DUPLICATE."

        Claim: duplicate reviewer_ids -> ERR_REVIEWER_DUPLICATE.
        """
        sch, app, _ = _build_pass_state()
        rs = create_reviewer_set(2, department_code="REV-DEPT")
        resp = api_client.assign_reviewers(
            sch["id"], app["id"],
            assign_reviewers_payload(
                reviewer_ids=[rs[0]["id"], rs[0]["id"], rs[1]["id"]],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_DUPLICATE.value)


class TestAssignReviewerCOI:

    def test_same_department_reviewer_rejected(self):
        """PRD §3.5: "the reviewer's department_code must differ from the
        application's student_department_code (the same-department
        check)".

        Claim: any of the three reviewers shares department -> 409
        ERR_COI_VIOLATION.
        """
        student_dept = "STU-COI-DEPT"
        sch, app, _ = _build_pass_state(
            student_dept=student_dept, reviewer_dept="REV-COI",
        )
        # Two safe reviewers + one COI-violating same-dept reviewer.
        ok = create_reviewer_set(2, department_code="REV-COI")
        coi_r = create_reviewer(department_code=student_dept)
        resp = api_client.assign_reviewers(
            sch["id"], app["id"],
            assign_reviewers_payload(
                reviewer_ids=[ok[0]["id"], ok[1]["id"], coi_r["id"]],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_COI_VIOLATION.value)

    def test_same_supervisor_reviewer_rejected(self):
        """PRD §3.5: "the reviewer's id must not equal the application's
        student_advisor_id (the same-supervisor check)".

        Claim: a reviewer whose id == student_advisor_id -> 409
        ERR_COI_VIOLATION.
        """
        student_dept = "STU-SUPER"
        reviewer_dept = "REV-SUPER"
        # Build the advisor reviewer first.
        advisor = create_reviewer(department_code=reviewer_dept)
        sch, app, _ = _build_pass_state(
            student_dept=student_dept, reviewer_dept=reviewer_dept,
            advisor_id=advisor["id"],
        )
        ok = create_reviewer_set(2, department_code=reviewer_dept)
        resp = api_client.assign_reviewers(
            sch["id"], app["id"],
            assign_reviewers_payload(
                reviewer_ids=[ok[0]["id"], ok[1]["id"], advisor["id"]],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_COI_VIOLATION.value)

    def test_family_relation_reviewer_rejected(self):
        """PRD §3.5: "the application's student_id must not appear in the
        reviewer's family_relation_student_ids array (the family-relation
        check)".

        Claim: reviewer.family_relation_student_ids contains student_id
        -> 409 ERR_COI_VIOLATION.
        """
        student_dept = "STU-FAM"
        reviewer_dept = "REV-FAM"
        # First we need the student_id to build the COI reviewer.
        sid = new_student_id()
        # Build reviewer with this family relation BEFORE we open the
        # scholarship so we can use it in assignment.
        family_r = create_reviewer(
            department_code=reviewer_dept,
            family_relation_student_ids=[sid],
        )
        sch, _ = create_open_scholarship(
            category="MERIT",
            required_materials=["TRANSCRIPT"],
            department_code=student_dept,
            gpa_threshold_x100=0,
        )
        app, _ = create_submitted_application(
            sch, student_id=sid,
            student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        close_and_review(sch)
        dept_review_pass(
            sch["id"], app["id"],
            dept_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        ok = create_reviewer_set(2, department_code=reviewer_dept)
        resp = api_client.assign_reviewers(
            sch["id"], app["id"],
            assign_reviewers_payload(
                reviewer_ids=[ok[0]["id"], ok[1]["id"], family_r["id"]],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_COI_VIOLATION.value)

    def test_suspended_reviewer_rejected(self):
        """PRD §3.5: "Each of the three reviewers' status must equal
        ACTIVE; otherwise ERR_REVIEWER_NOT_ACTIVE."

        Claim: an assigned reviewer with status=SUSPENDED -> 409
        ERR_REVIEWER_NOT_ACTIVE.
        """
        sch, app, _ = _build_pass_state()
        reviewers = create_reviewer_set(3, department_code="REV-DEPT")
        # Suspend the third reviewer.
        validate_success(
            api_client.patch_reviewer(
                reviewers[2]["id"],
                {"status": "SUSPENDED",
                 "version": reviewers[2]["version"]},
                ADMIN,
            ),
        )
        resp = api_client.assign_reviewers(
            sch["id"], app["id"],
            assign_reviewers_payload(
                reviewer_ids=[r["id"] for r in reviewers],
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_NOT_ACTIVE.value)

    def test_assign_success_transitions_to_under_review(self):
        """PRD §3.5: "On success the server creates three
        ReviewerAssignment rows — each carrying application_id,
        reviewer_id, and assigned_at — and the application transitions
        DEPT_PRELIM_PASSED → UNDER_REVIEW."

        Claim: valid assignment -> Application.status = UNDER_REVIEW.
        """
        sch, app, _ = _build_pass_state()
        reviewers = create_reviewer_set(3, department_code="REV-DEPT")
        result = assign_three_reviewers(sch["id"], app["id"], reviewers)
        assert result["status"] == "UNDER_REVIEW"


class TestDeptScopePass:
    """PRD §3.4 SAME-DEPT path. We omit a mismatch-rejection test
    because PRD §2.1 says DeptOfficer X-User-ID is opaque and 'does not
    compare these opaque identifiers to any entity's id'; PRD does not
    fix the mechanism by which the server identifies a DeptOfficer's
    department, so a PRD-only reader could ship a valid implementation
    that resolves it via several different conventions. We exercise the
    happy path here and rely on the difficulty-design tests in
    test_11 for cases where state takes precedence over scope.
    """

    def test_matching_dept_officer_passes_application(self):
        """PRD §3.4: "A successful PASS transitions SUBMITTED →
        DEPT_PRELIM_PASSED, overwrites the application's
        dept_review_comment with the supplied comment (which may be
        empty on PASS), and records an AuditEvent with event_type
        DEPT_REVIEW and payload.decision equal to PASS."

        Claim: dept-review PASS on a SUBMITTED application -> status
        becomes DEPT_PRELIM_PASSED.
        """
        student_dept = "STU-SCOPE"
        sch, _ = create_open_scholarship(
            category="MERIT", required_materials=["TRANSCRIPT"],
            department_code=student_dept,
            gpa_threshold_x100=0,
        )
        app, _ = create_submitted_application(
            sch, student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        close_and_review(sch)
        result = dept_review_pass(
            sch["id"], app["id"],
            dept_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        assert result["status"] == "DEPT_PRELIM_PASSED"
