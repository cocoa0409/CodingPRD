"""Severity override request/approve/reject workflow, including the
segregation-of-duties rule and the priority/SLA recomputation cascade
that fires on approval.
"""
from __future__ import annotations

import math

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_severity_override,
    assert_severity_override,
    create_defect,
    create_team_member,
    effective_resolution_sla,
    effective_response_sla,
    fetch_defect,
    find_audit_entries,
    list_audit_entries,
    make_developer_headers,
    make_triage_manager_headers,
    request_severity_override,
    setup_basic_module,
    setup_defect_in_state,
    severity_override_payload,
    severity_priority_score,
)


class TestSeverityOverrideRequest:
    def test_request_override_creates_pending(self):
        """PRD §3.3: "Any Developer, QAEngineer, or TriageManager may
        file a SeverityOverride against a defect, supplying a
        requested_severity ... The override is born in status PENDING
        with requested_by set to the caller's X-User-ID."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module, severity="MAJOR")
        resp = api_client.request_severity_override(
            defect["id"],
            severity_override_payload(requested_severity="BLOCKER"),
            team.developer_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_severity_override(data)
        assert data["status"] == "PENDING"
        assert data["requested_by"] == team.developer["id"]
        assert data["requested_severity"] == "BLOCKER"

    def test_override_with_same_severity_rejected(self):
        """PRD §3.3: "supplying a requested_severity (a different enum
        value from the defect's current effective_severity — proposing
        the same severity is rejected with ERR_OVERRIDE_NO_CHANGE)".
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module, severity="MAJOR")
        resp = api_client.request_severity_override(
            defect["id"],
            severity_override_payload(requested_severity="MAJOR"),
            team.developer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OVERRIDE_NO_CHANGE.value)


class TestSeverityOverrideApproval:
    def test_approve_changes_effective_severity_and_score(self):
        """PRD §3.3: "the parent defect's effective_severity is set to the
        override's requested_severity. That severity change triggers a
        recomputation of the defect's priority_score, which in turn
        drives a recomputation of response_due_minute and
        resolution_due_minute".
        """
        team, module = setup_basic_module()
        defect = create_defect(
            team, module,
            severity="MAJOR", business_impact="INTERNAL",
        )
        # MAJOR + INTERNAL + age 0 + 0 reopens = 40+5+0+0 = 45
        # multiplier 1.5 (relaxed), resp base 240 -> 360, resol base 1440 -> 2160
        assert defect["priority_score"] == 45
        assert defect["response_due_minute"] == math.ceil(240 * 1.5)
        assert defect["resolution_due_minute"] == math.ceil(1440 * 1.5)

        override = request_severity_override(
            team, defect,
            requested_severity="BLOCKER",
            requester=team.developer,
        )
        # Approver must be a TriageManager AND independent of requested_by.
        # team.triage != team.developer, so this is allowed.
        approved = approve_severity_override(team, override)
        assert approved["status"] == "APPROVED"
        assert approved["approved_by"] == team.triage["id"]

        d_after = fetch_defect(team, defect["id"])
        assert d_after["effective_severity"] == "BLOCKER"
        # BLOCKER + INTERNAL + age 0 + 0 reopens = 100+5+0+0 = 105
        # multiplier 1.0 (standard, since 80 <= 105 < 150)
        # Response base 30 -> 30, resolution base 240 -> 240
        expected_score = severity_priority_score(
            "BLOCKER", "INTERNAL", age_minutes=0, reopen_count=0,
        )
        assert d_after["priority_score"] == expected_score == 105
        # PRD §3.3: due-dates are recomputed RELATIVE TO ORIGINAL report time,
        # i.e., report_clock_minute (0 here).
        assert d_after["response_due_minute"] == 0 + effective_response_sla(
            "BLOCKER", 105,
        )
        assert d_after["resolution_due_minute"] == 0 + effective_resolution_sla(
            "BLOCKER", 105,
        )

    def test_approver_must_be_independent(self):
        """PRD §3.3: "the operator who approves or rejects the override
        must not be the same TeamMember who requested it. If X-User-ID
        on the approve or reject call equals the override's requested_by,
        the operation is refused with
        ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module, severity="MAJOR")
        # Create a TriageManager who is ALSO the requester: they file
        # the override using their own TriageManager id.
        triage_two = create_team_member(
            team.project, "TRIAGE_MANAGER",
            triage_headers=team.triage_headers,
        )
        override = request_severity_override(
            team, defect, requested_severity="BLOCKER",
            requester=triage_two,
        )
        # Now triage_two tries to approve their own request.
        resp = api_client.approve_severity_override(
            override["id"],
            make_triage_manager_headers(triage_two["id"]),
        )
        validate_error(
            resp,
            ApiErrorId.ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT.value,
        )

    def test_approve_on_closed_defect_rejected(self):
        """PRD §3.3: "The parent defect must not be in terminal CLOSED
        state — an override on a closed defect is rejected with
        ERR_DEFECT_CLOSED."

        Note: the rule applies to /approve and /reject, since the
        prose says 'Approval and rejection are both reserved to a
        TriageManager, but with one critical rule ... The parent defect
        must not be in terminal CLOSED state — an override on a closed
        defect is rejected with ERR_DEFECT_CLOSED.'
        """
        team, module = setup_basic_module()
        # Create defect, request override (still PENDING), then drive
        # the defect to CLOSED without approving.
        defect = setup_defect_in_state(team, module, "NEW")
        override = request_severity_override(
            team, defect, requested_severity="BLOCKER",
        )
        # Drive defect through to CLOSED:
        from test_helpers import (
            assign_defect, start_progress, submit_fix, verify_defect,
            close_defect,
        )
        assign_defect(team, defect)
        start_progress(team, defect)
        submit_fix(team, defect)
        verify_defect(team, defect, outcome="PASSED")
        close_defect(team, defect)
        # Now defect is CLOSED, override still PENDING.
        resp = api_client.approve_severity_override(
            override["id"], team.triage_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEFECT_CLOSED.value)

    def test_approve_already_terminal_override_rejected(self):
        """PRD §3.3: "Once an override reaches either terminal state, it
        cannot be revisited: a second approve or reject attempt is
        rejected with ERR_OVERRIDE_NOT_PENDING."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module, severity="MAJOR")
        override = request_severity_override(
            team, defect, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, override)  # now APPROVED
        # Second approve should be refused.
        resp = api_client.approve_severity_override(
            override["id"], team.triage_headers,
        )
        validate_error(resp, ApiErrorId.ERR_OVERRIDE_NOT_PENDING.value)


class TestSeverityOverrideRejection:
    def test_reject_leaves_defect_unchanged(self):
        """PRD §3.3: "Rejection moves the override to REJECTED, leaves
        the parent defect untouched".
        """
        team, module = setup_basic_module()
        defect = create_defect(
            team, module, severity="MAJOR", business_impact="INTERNAL",
        )
        score_before = defect["priority_score"]
        sev_before = defect["effective_severity"]
        override = request_severity_override(
            team, defect, requested_severity="BLOCKER",
            requester=team.developer,
        )
        resp = api_client.reject_severity_override(
            override["id"], team.triage_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        d_after = fetch_defect(team, defect["id"])
        assert d_after["effective_severity"] == sev_before
        assert d_after["priority_score"] == score_before


class TestApprovedOverrideAuditEntry:
    def test_approval_emits_severity_change_audit(self):
        """PRD §3.3: "An AuditEntry of event_type SEVERITY_CHANGE is
        appended carrying the prior and new effective_severity as
        from_value and to_value."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module, severity="MAJOR")
        override = request_severity_override(
            team, defect, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, override)
        entries = list_audit_entries(
            team, defect_id=defect["id"], event_type="SEVERITY_CHANGE",
        )
        hits = find_audit_entries(
            entries, from_value="MAJOR", to_value="BLOCKER",
        )
        assert hits, (
            "Expected SEVERITY_CHANGE audit with from=MAJOR, to=BLOCKER"
        )
