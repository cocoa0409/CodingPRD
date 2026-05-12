"""Modify / withdraw / correct cycles + the SUBMITTED<->DRAFT and
SUBMITTED->DEPT_PRELIM_REJECTED->SUBMITTED loops.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock,
    api_client,
    close_and_review,
    correct_application_payload,
    create_open_scholarship,
    create_submitted_application,
    dept_review_payload,
    dept_review_reject,
    make_dept_officer_headers,
    new_student_id,
    open_scholarship,
    validate_error,
    validate_success,
)


class TestModifyAndWithdraw:
    """PRD §3.3 SUBMITTED<->DRAFT and SUBMITTED->WITHDRAWN paths."""

    def test_modify_sends_back_to_draft(self):
        """PRD §3.3: "The modify capability transitions SUBMITTED → DRAFT,
        subject to the same window check (ERR_WINDOW_CLOSED outside the
        window), and emits no audit event because it is a precursor to a
        later re-submission."

        Claim: POST /modify on SUBMITTED -> status=DRAFT.
        """
        sch, _ = create_open_scholarship()
        app, headers = create_submitted_application(sch)
        result = validate_success(
            api_client.modify_application(sch["id"], app["id"], headers),
        )
        assert result["status"] == "DRAFT"

    def test_withdraw_transitions_to_withdrawn(self):
        """PRD §3.3: "The withdraw capability transitions SUBMITTED →
        WITHDRAWN and is permitted only while the logical "now" is
        strictly earlier than application_window_end (else
        ERR_WINDOW_CLOSED)."

        Claim: withdraw inside window -> status=WITHDRAWN.
        """
        sch, _ = create_open_scholarship()
        app, headers = create_submitted_application(sch)
        result = validate_success(
            api_client.withdraw_application(
                sch["id"], app["id"], headers,
            ),
        )
        assert result["status"] == "WITHDRAWN"

    def test_modify_after_window_closed_rejected(self):
        """PRD §3.3: "The modify capability transitions SUBMITTED → DRAFT,
        subject to the same window check (ERR_WINDOW_CLOSED outside the
        window)".

        Claim: clock past application_window_end -> modify rejected with
        ERR_WINDOW_CLOSED.
        """
        sch, _ = create_open_scholarship()
        app, headers = create_submitted_application(sch)
        advance_clock(sch["application_window_end"])
        resp = api_client.modify_application(sch["id"], app["id"], headers)
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED.value)

    def test_withdraw_after_window_closed_rejected(self):
        """PRD §3.3: "The withdraw capability transitions SUBMITTED →
        WITHDRAWN and is permitted only while the logical "now" is
        strictly earlier than application_window_end (else
        ERR_WINDOW_CLOSED)".

        Claim: clock past application_window_end -> withdraw rejected
        with ERR_WINDOW_CLOSED.
        """
        sch, _ = create_open_scholarship()
        app, headers = create_submitted_application(sch)
        advance_clock(sch["application_window_end"])
        resp = api_client.withdraw_application(
            sch["id"], app["id"], headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED.value)


class TestCorrectionCycle:
    """PRD §3.4 correction loop SUBMITTED → DEPT_PRELIM_REJECTED →
    SUBMITTED."""

    def test_correct_after_rejection_returns_to_submitted_and_clears_comment(self):
        """PRD §3.4: "The correction capability transitions
        DEPT_PRELIM_REJECTED → SUBMITTED for re-review. ... The side
        effect of a successful correction is to clear the application's
        dept_review_comment to null."

        Claim: after dept-review REJECT followed by /correct, status ==
        SUBMITTED and dept_review_comment == null.
        # difficulty: non_linear_state_machine/application_correction_cycle_revert
        """
        student_dept = "DEPT-CYCLE"
        sch, _ = create_open_scholarship(
            category="MERIT",
            required_materials=["TRANSCRIPT", "AWARD_CERT"],
            gpa_threshold_x100=0,
            department_code=student_dept,
        )
        app, student_headers = create_submitted_application(
            sch,
            student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT", "AWARD_CERT"],
        )
        close_and_review(sch)
        dept_review_reject(
            sch["id"], app["id"],
            dept_code=student_dept,
            comment="AWARD_CERT looks suspicious",
        )
        # Now the student corrects.
        result = validate_success(
            api_client.correct_application(
                sch["id"], app["id"],
                correct_application_payload(
                    replaced_materials=["AWARD_CERT"],
                ),
                student_headers,
            ),
        )
        assert result["status"] == "SUBMITTED"
        assert result.get("dept_review_comment") is None, (
            "PRD §3.4: 'clear the application's dept_review_comment to "
            "null'"
        )

    def test_correct_with_unknown_material_rejected(self):
        """PRD §3.4: "It accepts a replaced_materials array, each entry
        of which must already be present in the application's current
        uploaded_materials (else ERR_MATERIAL_MISSING)".

        Claim: /correct with a material not in uploaded_materials ->
        ERR_MATERIAL_MISSING.
        """
        student_dept = "DEPT-CYCLE-2"
        sch, _ = create_open_scholarship(
            category="MERIT",
            required_materials=["TRANSCRIPT"],
            department_code=student_dept,
            gpa_threshold_x100=0,
        )
        app, student_headers = create_submitted_application(
            sch,
            student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        close_and_review(sch)
        dept_review_reject(
            sch["id"], app["id"],
            dept_code=student_dept,
        )
        resp = api_client.correct_application(
            sch["id"], app["id"],
            correct_application_payload(
                replaced_materials=["POVERTY_PROOF"],
            ),
            student_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MATERIAL_MISSING.value)


class TestDeptReviewChecks:

    def test_dept_review_reject_with_empty_comment_rejected(self):
        """PRD §3.4: "On a REJECT, the officer's comment must be a
        non-empty string (else ERR_COMMENT_REQUIRED)".

        Claim: dept-review REJECT with empty comment -> ERR_COMMENT_REQUIRED.
        """
        student_dept = "DEPT-EMPTY-COMMENT"
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
        officer_headers = make_dept_officer_headers(
            f"dept-officer-{student_dept}",
        )
        resp = api_client.dept_review_application(
            sch["id"], app["id"],
            dept_review_payload(decision="REJECT", comment=""),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_COMMENT_REQUIRED.value)

    def test_dept_review_pass_with_authenticity_false_rejected(self):
        """PRD §3.4: "On a PASS, the server additionally re-checks
        completeness — uploaded_materials must still be a superset of
        required_materials, and every entry in is_authentic_flags
        corresponding to a required material must be true; either failure
        yields ERR_MATERIAL_INCOMPLETE."

        Claim: dept-review PASS with is_authentic_flags[TRANSCRIPT]=false
        -> ERR_MATERIAL_INCOMPLETE.
        """
        student_dept = "DEPT-AUTH-FAIL"
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
        officer_headers = make_dept_officer_headers(
            f"dept-officer-{student_dept}",
        )
        resp = api_client.dept_review_application(
            sch["id"], app["id"],
            dept_review_payload(
                decision="PASS", comment="",
                is_authentic_flags={"TRANSCRIPT": False},
            ),
            officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MATERIAL_INCOMPLETE.value)
