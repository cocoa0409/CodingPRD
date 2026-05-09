"""Audit logging (PRD §2.10, §3.7 cycle observation)."""
import pytest

from test_helpers import (
    validate_paginated,
    get_success_data,
    create_active_student,
    file_complaint,
    file_and_assign_complaint,
    assign_handler_payload,
    ADMIN_HEADERS,
    make_handler_headers,
)


class TestAuditLogFiltering:

    def test_audit_log_filterable_by_entity_type_and_id(self, api):
        """PRD §2.10: "The audit-log listing capability supports filtering by
        query parameters entity_type and entity_id, plus pagination via limit
        and offset."

        Claim: filtering by entity_type=Complaint and entity_id={id} returns
        the complaint's audit rows.
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING")

        resp = api.list_audit_logs(ADMIN_HEADERS,
                                     params={"entity_type": "Complaint",
                                             "entity_id": complaint["id"]})
        data, meta = validate_paginated(resp)
        # At least one CREATE row for this complaint
        assert all(r["entity_type"] == "Complaint" for r in data)
        assert all(r["entity_id"] == complaint["id"] for r in data)
        actions = {r["action"] for r in data}
        assert "CREATE" in actions

    def test_complaint_assignment_and_escalation_logged(self, api):
        """PRD §3.7 + §2.10: assign-handler writes ASSIGN_HANDLER; escalate
        writes ESCALATE.
        # difficulty: non_linear_state_machine/complaint_in_review_to_escalated_cycle
        Claim: at least 4 entries observed across two assign+escalate iterations.
        """
        student, _ = create_active_student(api)
        complaint = file_complaint(api, student=student, category="BILLING")

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

        resp = api.list_audit_logs(ADMIN_HEADERS,
                                     params={"entity_type": "Complaint",
                                             "entity_id": complaint["id"],
                                             "limit": 100})
        data, _ = validate_paginated(resp)
        actions = [r["action"] for r in data]
        assert actions.count("ASSIGN_HANDLER") >= 2
        assert actions.count("ESCALATE") >= 2
