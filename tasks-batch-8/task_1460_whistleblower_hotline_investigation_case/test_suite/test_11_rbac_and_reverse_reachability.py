"""RBAC denials across roles and case-child reverse-reachability listings."""
from test_helpers import (
    ApiErrorId,
    add_conducted_interview,
    add_determination,
    create_case,
    create_evidence_payload,
    create_interview_payload,
    create_report_payload,
    create_staff,
    make_acm_headers,
    make_officer_headers,
    make_reporter_headers,
    setup_case_under_investigation,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestReporterDenials:
    def test_reporter_cannot_list_cases(self, api):
        """PRD §2.1: "If the role is valid but not permitted for the target endpoint,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        (PRD §4 endpoint table: GET /hotline/cases is staff-only; HotlineReporter
        is not among the authorized roles.)

        Design: Corner/rbac/reporter_cannot_list_cases
        """
        _case, key = create_case()
        resp = api.list_cases(make_reporter_headers(key))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestAuditCommitteeMember:
    def test_acm_can_list_reports(self, api):
        """PRD §3.9: "Reports can be listed with optional `status` filtering and
        pagination; the audit trail endpoint of §2.10 is also open to committee
        members". (PRD §4 authorizes AuditCommitteeMember for
        GET /hotline/audit-committee-reports.)

        Design: Corner/rbac/acm_can_list_reports_but_cannot_create
        """
        s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
        api.create_audit_report(create_report_payload(), make_officer_headers(s_off["id"]))
        resp = api.list_audit_reports(make_acm_headers())
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1

    def test_acm_cannot_create_report(self, api):
        """PRD §2.1: "If the role is valid but not permitted for the target endpoint,
        the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        (PRD §4 authorizes only ComplianceOfficer for
        POST /hotline/audit-committee-reports.)

        Design: Corner/rbac/acm_can_list_reports_but_cannot_create
        """
        resp = api.create_audit_report(create_report_payload(), make_acm_headers())
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestReverseReachability:
    def test_child_lists_return_one_row_each(self, api):
        """PRD §1: "reverse reachability (for example, listing the interviews of a
        case) is provided through nested list endpoints". PRD §3.4: "All
        assignments of a case can be listed with optional `status` filtering and
        standard pagination."

        Design: Corner/endpoints/fk_reverse_reachability_lists_return_children
        """
        ctx = setup_case_under_investigation()
        staff = ctx["staff"]
        api.create_interview(create_interview_payload(ctx["case"]["id"]), staff["h_inv"])
        api.create_evidence_item(create_evidence_payload(ctx["case"]["id"]), staff["h_inv"])
        add_determination(ctx, finding="INCONCLUSIVE",
                          rationale="Draft written to exercise the reverse-reachability listing endpoints.")
        asg_rows = api.list_assignments(ctx["case"]["id"], staff["h_off"]).json()["data"]
        iv_rows = api.list_interviews(ctx["case"]["id"], staff["h_off"]).json()["data"]
        ev_rows = api.list_evidence_items(ctx["case"]["id"], staff["h_off"]).json()["data"]
        det_rows = api.list_determinations(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert len(asg_rows) == 1 and asg_rows[0]["status"] == "ACTIVE"
        assert asg_rows[0]["investigator_id"] == staff["s_inv"]["id"]
        assert len(iv_rows) == 1 and iv_rows[0]["status"] == "SCHEDULED"
        assert len(ev_rows) == 1 and ev_rows[0]["status"] == "PRESERVED"
        assert len(det_rows) == 1 and det_rows[0]["status"] == "DRAFT"
