"""Complaints lifecycle and multi-level escalation (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_student,
    create_default_package,
    file_complaint,
    file_and_assign_complaint,
    assign_handler_payload,
    resolve_complaint_payload,
    reject_complaint_payload,
    ADMIN_HEADERS,
    make_student_headers,
    make_handler_headers,
    get_complaint,
)


class TestComplaintFiling:

    def test_student_files_complaint(self, api):
        """PRD §3.7: "A Complaint carries student_id ... category ... description.
        ... Filing a complaint is allowed for a Student (only with student_id
        matching their X-User-ID) or for an Admin."
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING",
                                     description="Wrong charge")
        assert complaint["status"] == "OPEN"
        assert complaint["level"] == 1
        assert complaint["category"] == "BILLING"


class TestAssignHandler:

    def test_assign_handler_open_to_in_review(self, api):
        """PRD §3.7: "An admin assigns a handler to an OPEN complaint,
        transitioning it to IN_REVIEW ... assigned_handler_id and
        assigned_handler_role are set from the body."
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING")
        resp = api.assign_handler(complaint["id"],
                                    assign_handler_payload(handler_id="handler_01",
                                                            handler_role="ComplaintHandler"),
                                    ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["status"] == "IN_REVIEW"
        assert data["assigned_handler_id"] == "handler_01"
        assert data["assigned_handler_role"] == "ComplaintHandler"

    def test_instructor_conduct_requires_admin_handler(self, api):
        """PRD §3.7: "when the complaint's category is INSTRUCTOR_CONDUCT,
        handler_role must be Admin — handing an instructor-conduct complaint
        to a ComplaintHandler is rejected with
        ERR_INSTRUCTOR_COMPLAINT_REQUIRES_ADMIN."
        """
        from test_helpers import create_active_instructor
        student, _ = create_active_student(api)
        instructor = create_active_instructor(api)
        complaint = file_complaint(api, student=student,
                                     category="INSTRUCTOR_CONDUCT",
                                     description="Rude",
                                     instructor_id=instructor["id"])
        resp = api.assign_handler(complaint["id"],
                                    assign_handler_payload(handler_id="handler_01",
                                                            handler_role="ComplaintHandler"),
                                    ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_COMPLAINT_REQUIRES_ADMIN.value)

    def test_assign_handler_state_gate(self, api):
        """PRD §3.7: "If the complaint's status is not in {OPEN, ESCALATED} at
        this point, the request is rejected with ERR_COMPLAINT_NOT_ASSIGNABLE."
        """
        student, _ = create_active_student(api)
        complaint = file_and_assign_complaint(api, student=student, handler_id="handler_01")
        # complaint is now IN_REVIEW; assign-handler again rejected
        resp = api.assign_handler(complaint["id"],
                                    assign_handler_payload(handler_id="handler_02",
                                                            handler_role="ComplaintHandler"),
                                    ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_ASSIGNABLE.value)


class TestEscalation:
    """PRD §3.7 Complaint cycle: OPEN → IN_REVIEW → ESCALATED → IN_REVIEW (re-assigned)
    → ... up to level 3.
    # difficulty: non_linear_state_machine/complaint_in_review_to_escalated_cycle
    """

    def test_escalate_increments_level_and_clears_handler(self, api):
        """PRD §3.7: "level increments by 1; status becomes ESCALATED;
        escalated_at is set to the logical clock; both assigned_handler_id and
        assigned_handler_role are cleared so that an admin must re-assign."
        """
        student, _ = create_active_student(api)
        complaint = file_and_assign_complaint(api, student=student, handler_id="handler_01")
        resp = api.escalate_complaint(complaint["id"],
                                        make_handler_headers("handler_01"))
        data = validate_success(resp)
        assert data["status"] == "ESCALATED"
        assert data["level"] == 2
        assert data["escalated_at"] is not None
        assert data["assigned_handler_id"] is None
        assert data["assigned_handler_role"] is None

    def test_in_review_to_escalated_cycle(self, api):
        """PRD §3.7 escalation cycle: OPEN→IN_REVIEW→ESCALATED→IN_REVIEW→ESCALATED.
        Level monotonically increases; status returns to IN_REVIEW after
        re-assignment.

        Claim: cycle observed for two iterations; level reaches 3.
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING")

        # Step 1: assign handler_01 — OPEN → IN_REVIEW, level=1
        c1 = get_success_data(api.assign_handler(complaint["id"],
                                                  assign_handler_payload(handler_id="handler_01",
                                                                          handler_role="ComplaintHandler"),
                                                  ADMIN_HEADERS))
        assert c1["status"] == "IN_REVIEW"
        assert c1["level"] == 1

        # Step 2: escalate — IN_REVIEW → ESCALATED, level=2
        c2 = get_success_data(api.escalate_complaint(complaint["id"],
                                                      make_handler_headers("handler_01")))
        assert c2["status"] == "ESCALATED"
        assert c2["level"] == 2

        # Step 3: re-assign handler_02 — ESCALATED → IN_REVIEW, level still 2
        c3 = get_success_data(api.assign_handler(complaint["id"],
                                                  assign_handler_payload(handler_id="handler_02",
                                                                          handler_role="ComplaintHandler"),
                                                  ADMIN_HEADERS))
        assert c3["status"] == "IN_REVIEW"
        assert c3["level"] == 2

        # Step 4: escalate — IN_REVIEW → ESCALATED, level=3
        c4 = get_success_data(api.escalate_complaint(complaint["id"],
                                                      make_handler_headers("handler_02")))
        assert c4["status"] == "ESCALATED"
        assert c4["level"] == 3

    def test_escalation_limit_at_level_3(self, api):
        """PRD §3.7: "If the complaint's current level is already 3, escalation
        is rejected with ERR_ESCALATION_LIMIT_REACHED."
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING")

        get_success_data(api.assign_handler(complaint["id"],
                                              assign_handler_payload(handler_id="h1",
                                                                      handler_role="ComplaintHandler"),
                                              ADMIN_HEADERS))
        get_success_data(api.escalate_complaint(complaint["id"], make_handler_headers("h1")))

        # Level 2; reassign to admin (level 3 will require admin)
        get_success_data(api.assign_handler(complaint["id"],
                                              assign_handler_payload(handler_id="h2",
                                                                      handler_role="ComplaintHandler"),
                                              ADMIN_HEADERS))
        get_success_data(api.escalate_complaint(complaint["id"], make_handler_headers("h2")))

        # Now at level 3 ESCALATED. Reassign to admin (level 3 admin-only)
        get_success_data(api.assign_handler(complaint["id"],
                                              assign_handler_payload(handler_id="admin-002",
                                                                      handler_role="Admin"),
                                              ADMIN_HEADERS))

        # Try to escalate further — rejected
        from test_helpers import build_user_headers
        admin_h = build_user_headers("admin-002", "Admin")
        resp = api.escalate_complaint(complaint["id"], admin_h)
        validate_error(resp, ApiErrorId.ERR_ESCALATION_LIMIT_REACHED.value)

    def test_level3_requires_admin_handler(self, api):
        """PRD §3.7: "for any complaint whose current level is 3, handler_role
        must be Admin — escalated tier-3 complaints are admin-only and a
        ComplaintHandler assignment is rejected with ERR_LEVEL3_REQUIRES_ADMIN."
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING")

        # Walk to level 3 ESCALATED
        get_success_data(api.assign_handler(complaint["id"],
                                              assign_handler_payload(handler_id="h1",
                                                                      handler_role="ComplaintHandler"),
                                              ADMIN_HEADERS))
        get_success_data(api.escalate_complaint(complaint["id"], make_handler_headers("h1")))
        get_success_data(api.assign_handler(complaint["id"],
                                              assign_handler_payload(handler_id="h2",
                                                                      handler_role="ComplaintHandler"),
                                              ADMIN_HEADERS))
        get_success_data(api.escalate_complaint(complaint["id"], make_handler_headers("h2")))

        # Now level=3 ESCALATED. Re-assign to a ComplaintHandler — rejected.
        resp = api.assign_handler(complaint["id"],
                                    assign_handler_payload(handler_id="h3",
                                                            handler_role="ComplaintHandler"),
                                    ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_LEVEL3_REQUIRES_ADMIN.value)


class TestResolveReject:

    def test_handler_can_resolve_in_review(self, api):
        """PRD §3.7: "A ComplaintHandler or an Admin may move an IN_REVIEW
        complaint to RESOLVED (with body response_text and resolution_summary
        written onto the complaint, plus resolved_at set to the logical clock)."
        """
        student, _ = create_active_student(api)
        complaint = file_and_assign_complaint(api, student=student, handler_id="handler_01")
        resp = api.resolve_complaint(complaint["id"],
                                       resolve_complaint_payload(response_text="ok",
                                                                   resolution_summary="refunded"),
                                       make_handler_headers("handler_01"))
        data = validate_success(resp)
        assert data["status"] == "RESOLVED"
        assert data["response_text"] == "ok"
        assert data["resolution_summary"] == "refunded"
        assert data["resolved_at"] is not None

    def test_resolve_by_unassigned_handler_rejected(self, api):
        """PRD §3.7: "the acting handler's X-User-ID must equal
        assigned_handler_id (ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER)."
        """
        student, _ = create_active_student(api)
        complaint = file_and_assign_complaint(api, student=student, handler_id="handler_01")
        resp = api.resolve_complaint(complaint["id"],
                                       resolve_complaint_payload(response_text="x",
                                                                   resolution_summary="y"),
                                       make_handler_headers("handler_xx"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_ASSIGNED_HANDLER.value)

    def test_handler_can_reject_in_review(self, api):
        """PRD §3.7: "A ComplaintHandler or an Admin may move an IN_REVIEW
        complaint ... or to REJECTED (with body response_text only, plus
        resolved_at set)."
        """
        student, _ = create_active_student(api)
        complaint = file_and_assign_complaint(api, student=student, handler_id="handler_01")
        resp = api.reject_complaint(complaint["id"],
                                      reject_complaint_payload(response_text="no"),
                                      make_handler_headers("handler_01"))
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        assert data["response_text"] == "no"
        assert data["resolved_at"] is not None
