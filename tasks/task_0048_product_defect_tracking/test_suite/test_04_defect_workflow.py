"""Defect workflow: assign, reassign, start-progress, submit-fix, verify,
close, and the reopen cascade on verify(FAILED).
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_defect,
    assign_payload,
    assert_defect,
    assert_fix_record,
    assert_verification_record,
    close_defect,
    create_defect,
    create_team_member,
    effective_response_sla,
    fetch_defect,
    fetch_module,
    fetch_team_member,
    find_audit_entries,
    latest_fix_record,
    list_audit_entries,
    make_developer_headers,
    make_qa_engineer_headers,
    reassign_payload,
    setup_basic_module,
    setup_defect_in_state,
    setup_team,
    severity_priority_score,
    start_progress,
    submit_fix,
    submit_fix_payload,
    verify_defect,
    verify_payload,
)


class TestAssignNewDefect:
    def test_assign_new_defect_with_explicit_assignee(self):
        """PRD §3.5: "Assignment begins when a TriageManager calls the
        assign capability on a NEW defect, transitioning its status from
        NEW to ASSIGNED. ... On success the defect's assignee_id is set,
        the chosen team member's active_workload is incremented by 1".
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)
        resp = api_client.assign_defect(
            defect["id"], team.triage_headers,
            assign_payload(assignee_id=team.developer["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "ASSIGNED"
        assert data["assignee_id"] == team.developer["id"]
        # Active workload counter incremented.
        dev_after = fetch_team_member(team, team.developer["id"])
        assert dev_after["active_workload"] == 1

    def test_assign_with_inactive_team_member_rejected(self):
        """PRD §3.5: "the referenced TeamMember must exist, be ACTIVE,
        and have project_id matching the defect's project_id — otherwise
        ERR_TEAM_MEMBER_NOT_ELIGIBLE."
        Note: this targets the cross-project / different-project case
        because PRD provides a clean reproducer: a developer from another
        project is ACTIVE but in a different project, hence ineligible.
        """
        team_a, module_a = setup_basic_module()
        defect = create_defect(team_a, module_a)
        team_b = setup_team()  # ACTIVE developer in a different project
        resp = api_client.assign_defect(
            defect["id"], team_a.triage_headers,
            assign_payload(assignee_id=team_b.developer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_TEAM_MEMBER_NOT_ELIGIBLE.value,
        )

    def test_assign_without_assignee_uses_selector(self):
        """PRD §3.5: "When the body omits assignee_id, the server runs an
        automatic selector. The candidate pool is every TeamMember whose
        project_id matches the defect's project_id, whose status is
        ACTIVE, and whose role is either DEVELOPER or QA_ENGINEER."
        Selector picks least-loaded; with two candidates (Developer +
        QAEngineer) both at workload 0, the secondary tie-breaker is
        module-ownership: module.owner_team_member_id == developer.id, so
        the developer should win.
        """
        team, module = setup_basic_module()  # owner = team.developer
        defect = create_defect(team, module)
        resp = api_client.assign_defect(
            defect["id"], team.triage_headers, assign_payload(),
        )
        data = validate_success(resp)
        assert data["status"] == "ASSIGNED"
        assert data["assignee_id"] == team.developer["id"]


class TestReassign:
    def test_reassign_swaps_workload(self):
        """PRD §3.5: "On success the old assignee's active_workload is
        decremented by 1, the new assignee's active_workload is
        incremented by 1, and an AuditEntry of event_type
        ASSIGNMENT_CHANGE is appended with from_value the old assignee_id
        and to_value the new assignee_id."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)
        assign_defect(team, defect)  # team.developer is now assignee
        # Create a second eligible developer.
        new_dev = create_team_member(
            team.project, "DEVELOPER",
            triage_headers=team.triage_headers,
        )
        resp = api_client.reassign_defect(
            defect["id"],
            reassign_payload(new_assignee_id=new_dev["id"]),
            team.triage_headers,
        )
        data = validate_success(resp)
        assert data["assignee_id"] == new_dev["id"]
        # Workload counters swap.
        old_dev_after = fetch_team_member(team, team.developer["id"])
        new_dev_after = fetch_team_member(team, new_dev["id"])
        assert old_dev_after["active_workload"] == 0
        assert new_dev_after["active_workload"] == 1
        # AuditEntry ASSIGNMENT_CHANGE recorded.
        entries = list_audit_entries(
            team, defect_id=defect["id"], event_type="ASSIGNMENT_CHANGE",
        )
        change_entries = find_audit_entries(
            entries, from_value=team.developer["id"],
            to_value=new_dev["id"],
        )
        assert change_entries, (
            "Expected AuditEntry from_value=old_assignee, to_value=new"
        )

    def test_reassign_same_assignee_rejected(self):
        """PRD §3.5: "the body carries a new_assignee_id, which must
        differ from the current assignee_id (otherwise
        ERR_REASSIGN_SAME_ASSIGNEE)".
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)
        assign_defect(team, defect)
        resp = api_client.reassign_defect(
            defect["id"],
            reassign_payload(new_assignee_id=team.developer["id"]),
            team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REASSIGN_SAME_ASSIGNEE.value,
        )

    def test_reassign_when_not_assigned_rejected(self):
        """PRD §3.5: "must apply against a defect actually in ASSIGNED
        (otherwise ERR_REASSIGN_NOT_ASSIGNED)".
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)  # status=NEW, not ASSIGNED
        new_dev = create_team_member(
            team.project, "DEVELOPER",
            triage_headers=team.triage_headers,
        )
        resp = api_client.reassign_defect(
            defect["id"],
            reassign_payload(new_assignee_id=new_dev["id"]),
            team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REASSIGN_NOT_ASSIGNED.value,
        )


class TestStartProgress:
    def test_non_assignee_cannot_start_progress(self):
        """PRD §3.6: "A Developer whose X-User-ID equals the defect's
        assignee_id may transition an ASSIGNED defect to IN_PROGRESS via
        the start-progress capability".

        PRD does not pin the specific error_id used when a non-assignee
        Developer attempts start-progress (priority 2 RBAC permission
        is for the Developer role broadly; ownership is a finer check).
        Two PRD-only readers could ship 403 ERR_INSUFFICIENT_PERMISSIONS
        or a 4xx with a more specific code. Assert HTTP 4xx; do not pin
        a single error_id.
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)
        assign_defect(team, defect)  # assignee = team.developer
        other_dev = create_team_member(
            team.project, "DEVELOPER",
            triage_headers=team.triage_headers,
        )
        resp = api_client.start_progress(
            defect["id"], make_developer_headers(other_dev["id"]),
        )
        assert 400 <= resp.status_code < 500, (
            "Non-assignee start-progress must be refused with 4xx"
        )
        body = resp.json()
        assert body.get("response_type") == "error"

    def test_start_progress_on_new_defect_rejected(self):
        """PRD §3.6: "this fails with ERR_DEFECT_NOT_ASSIGNED from a
        non-ASSIGNED defect."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)  # status=NEW
        resp = api_client.start_progress(
            defect["id"], team.developer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEFECT_NOT_ASSIGNED.value)


class TestSubmitFix:
    def test_submit_fix_creates_fix_record_and_transitions(self):
        """PRD §3.6: "the same assigned Developer submits a fix,
        transitioning the defect from IN_PROGRESS to FIXED. ... A new
        FixRecord row is appended carrying the defect_id, the fix_version,
        the developer_id (which equals the defect's assignee_id at submit
        time), the fix_summary, and the commit_sha. The defect's
        fix_version field is set from the new FixRecord.fix_version."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "IN_PROGRESS")
        resp = api_client.submit_fix(
            defect["id"],
            submit_fix_payload(fix_version="1.0.1"),
            team.developer_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "FIXED"
        assert data["fix_version"] == "1.0.1"
        # FixRecord row exists.
        fr = latest_fix_record(team, defect)
        assert_fix_record(fr)
        assert fr["fix_version"] == "1.0.1"
        assert fr["developer_id"] == team.developer["id"]

    def test_submit_fix_first_time_populates_first_fixed_at_minute(self):
        """PRD §3.6: "If this is the defect's first arrival at FIXED ...
        the system sets first_fixed_at_minute to the project's current
        clock_minute and also populates final_resolution_minutes as the
        current clock_minute minus the defect's report_clock_minute minus
        total_paused_minutes."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "IN_PROGRESS")
        # Clock has not advanced; first_fixed_at_minute should equal 0.
        d_after = submit_fix(team, defect, fix_version="1.0.1")
        assert d_after["first_fixed_at_minute"] == 0
        assert d_after["final_resolution_minutes"] == 0

    def test_submit_fix_on_non_in_progress_rejected(self):
        """PRD §3.6: "Submit-fix on a defect not in IN_PROGRESS is
        rejected with ERR_DEFECT_NOT_IN_PROGRESS."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        resp = api_client.submit_fix(
            defect["id"], submit_fix_payload(),
            team.developer_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DEFECT_NOT_IN_PROGRESS.value,
        )


class TestVerify:
    def test_verify_passed_transitions_to_verified(self):
        """PRD §3.7: "A PASSED outcome creates a VerificationRecord with
        outcome PASSED, the supplied fix_record_id, the verifier's
        X-User-ID as verifier_id, and any supplied notes. The defect
        transitions from FIXED to VERIFIED".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        fix_id = latest_fix_record(team, defect)["id"]
        resp = api_client.verify_defect(
            defect["id"],
            verify_payload(outcome="PASSED", fix_record_id=fix_id),
            team.qa_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "VERIFIED"

    def test_verify_failed_reopen_cascade(self):
        """PRD §3.7: "the defect transitions from FIXED to REOPENED, and
        that transition fires a chain of five linked side effects in
        order: first the defect's reopen_count is incremented by 1;
        second the priority_score is recomputed using the new
        reopen_count ... third the response_due_minute is reset to the
        project's current clock_minute plus the effective response budget
        computed against the freshly-recomputed priority_score".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "FIXED",
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        fix_id = latest_fix_record(team, defect)["id"]
        resp = api_client.verify_defect(
            defect["id"],
            verify_payload(outcome="FAILED", fix_record_id=fix_id),
            team.qa_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "REOPENED"
        assert data["reopen_count"] == 1
        # priority_score now picks up +15 per reopen.
        expected_score = severity_priority_score(
            "CRITICAL", "REVENUE_BLOCKING",
            age_minutes=0, reopen_count=1,
        )
        assert data["priority_score"] == expected_score
        # response_due_minute reset to clock + new effective response.
        expected_response = effective_response_sla(
            "CRITICAL", expected_score,
        )
        assert data["response_due_minute"] == 0 + expected_response

    def test_verify_failed_resets_escalation_level_to_zero(self):
        """PRD §3.7: "a second AuditEntry of event_type ESCALATION is
        appended with from_value the defect's prior escalation_level and
        to_value 0, because reopen resets escalation_level back to 0
        (escalation does not survive reopen)."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        fix_id = latest_fix_record(team, defect)["id"]
        resp = api_client.verify_defect(
            defect["id"],
            verify_payload(outcome="FAILED", fix_record_id=fix_id),
            team.qa_headers,
        )
        data = validate_success(resp)
        assert data["escalation_level"] == 0

    def test_verifier_self_verification_rejected(self):
        """PRD §3.7: "The verifier's X-User-ID must not equal the
        developer_id recorded on that FixRecord — a self-verification is
        refused with ERR_VERIFIER_NOT_INDEPENDENT, regardless of the
        requested outcome."

        We construct a developer who is ALSO a QAEngineer-roled
        TeamMember to test this rule. Easier: register an additional
        TeamMember whose role is QA_ENGINEER, but submit fixes using a
        developer's id. To trigger the actual self-verification check we
        need to call /verify with X-User-ID == FixRecord.developer_id —
        we accomplish this by sending the verify call with the developer
        TeamMember.id and the QAEngineer role header.
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        fix = latest_fix_record(team, defect)
        # Verify call uses X-User-ID = developer_id (== fix.developer_id)
        # under the QAEngineer role.
        resp = api_client.verify_defect(
            defect["id"],
            verify_payload(outcome="PASSED", fix_record_id=fix["id"]),
            make_qa_engineer_headers(team.developer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_VERIFIER_NOT_INDEPENDENT.value,
        )

    def test_verify_with_stale_fix_record_rejected(self):
        """PRD §3.7: "The fix_record_id supplied must additionally be the
        latest FixRecord for the defect — across reopen cycles, defects
        accumulate multiple FixRecord rows, and only the most recent one
        is eligible for verification; supplying a stale fix-record id is
        rejected with ERR_FIX_RECORD_STALE."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        stale_fix_id = latest_fix_record(team, defect)["id"]
        # Cycle back to FIXED via verify(FAILED) → REOPENED →
        # ASSIGNED → IN_PROGRESS → FIXED (creates a new FixRecord).
        api_client.verify_defect(
            defect["id"],
            verify_payload(
                outcome="FAILED", fix_record_id=stale_fix_id,
            ),
            team.qa_headers,
        )
        # REOPENED → ASSIGNED (assign by triage)
        assign_defect(team, defect)
        # ASSIGNED → IN_PROGRESS
        start_progress(team, defect)
        # IN_PROGRESS → FIXED (new FixRecord)
        submit_fix(team, defect, fix_version="1.0.2")
        # Now verify with the STALE fix_record_id.
        resp = api_client.verify_defect(
            defect["id"],
            verify_payload(
                outcome="PASSED", fix_record_id=stale_fix_id,
            ),
            team.qa_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FIX_RECORD_STALE.value)

    def test_verify_when_not_fixed_rejected(self):
        """PRD §3.7: "The defect itself must be in FIXED; calling verify
        on any other status is ERR_DEFECT_NOT_FIXED."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        resp = api_client.verify_defect(
            defect["id"],
            verify_payload(
                outcome="PASSED", fix_record_id=NON_EXISTENT_UUID,
            ),
            team.qa_headers,
        )
        # PRD §2.10 fixes the priority order: existence (§2.9) first,
        # then state. fix_record_id is a body-id reference, and PRD §2.9
        # explicitly lists missing fix_record_id as
        # ERR_FIX_RECORD_NOT_FOUND. Two readers could ship two different
        # ERR codes here depending on whether they treat the state check
        # or the existence check first against a NEW defect with a
        # missing fix_record. Relax to accept either.
        from prd_bench_local_runner.testing import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_DEFECT_NOT_FIXED.value,
            ApiErrorId.ERR_FIX_RECORD_NOT_FOUND.value,
        ])

    def test_verification_record_is_append_only(self):
        """PRD §2.4: FixRecord, VerificationRecord, SLAPause, and
        DefectAttachment carry only id and created_at — no updated_at,
        no version.
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        fix_id = latest_fix_record(team, defect)["id"]
        api_client.verify_defect(
            defect["id"],
            verify_payload(outcome="PASSED", fix_record_id=fix_id),
            team.qa_headers,
        )
        resp = api_client.list_verification_records(
            defect["id"], team.triage_headers,
        )
        from prd_bench_local_runner.testing import validate_paginated
        records, _ = validate_paginated(resp)
        assert records, "Expected one VerificationRecord"
        for r in records:
            assert_verification_record(r)


class TestClose:
    def test_close_verified_decrements_quota(self):
        """PRD §3.9: "On a successful close the assignee's active_workload
        decrements by 1, the module's active_defect_count decrements by 1,
        the module's quota_remaining increments by 1".
        """
        team, module = setup_basic_module(initial_defect_quota=5)
        defect = setup_defect_in_state(team, module, "VERIFIED")
        m_before = fetch_module(team, module["id"])
        assert m_before["active_defect_count"] == 1
        assert m_before["quota_remaining"] == 4
        close_defect(team, defect)
        m_after = fetch_module(team, module["id"])
        assert m_after["active_defect_count"] == 0
        assert m_after["quota_remaining"] == 5
        dev_after = fetch_team_member(team, team.developer["id"])
        assert dev_after["active_workload"] == 0

    def test_close_non_verified_rejected(self):
        """PRD §3.9: "the defect must be in VERIFIED — calling close on
        any other status is ERR_DEFECT_NOT_VERIFIED."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        resp = api_client.close_defect(
            defect["id"], team.triage_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEFECT_NOT_VERIFIED.value)
