"""SLA pause / resume mechanics, including adjacency-strict separation,
and the SLA-escalation sweep with strict greater-than boundary semantics.
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
    advance_clock,
    assert_elapsed_time_invariant,
    create_defect,
    fetch_defect,
    find_audit_entries,
    list_audit_entries,
    make_developer_headers,
    pause_sla,
    pause_sla_payload,
    resume_sla,
    run_escalation_sweep,
    setup_basic_module,
    setup_critical_defect_at_clock_zero,
    setup_defect_in_state,
)


class TestSlaPauseLifecycle:
    def test_pause_creates_sla_pause_row_and_transitions(self):
        """PRD §3.8: "On a successful pause the system creates a new
        SLAPause row with started_at_minute equal to the project's
        current clock_minute, ended_at_minute null, reason from the body,
        and paused_by from X-User-ID; the defect's sla_state transitions
        from RUNNING to PAUSED".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        resp = api_client.pause_sla(
            defect["id"],
            pause_sla_payload(reason="WAITING_ON_REPORTER"),
            team.developer_headers,
        )
        data = validate_success(resp)
        assert data["sla_state"] == "PAUSED"

    def test_resume_increments_total_paused_minutes(self):
        """PRD §3.8: "Resuming is also restricted to the assigned
        Developer. The system finds the open SLAPause row (the one with
        ended_at_minute null) for this defect, closes it by setting
        ended_at_minute to the project's current clock_minute, and
        increments the defect's total_paused_minutes by the difference
        between that closed ended_at_minute and the row's
        started_at_minute."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, defect)
        advance_clock(team.project, 10)
        d_after = resume_sla(team, defect)
        assert d_after["sla_state"] == "RUNNING"
        assert d_after["total_paused_minutes"] == 10
        assert_elapsed_time_invariant(d_after, project_clock_minute=10)

    def test_pause_on_new_defect_rejected(self):
        """PRD §3.8: "Pausing is only valid while the primary status is
        in ASSIGNED or IN_PROGRESS — calling pause on a defect in any
        other status is rejected with ERR_SLA_PAUSE_INVALID_STATUS."
        """
        team, module = setup_basic_module()
        defect = create_defect(team, module)  # status=NEW
        resp = api_client.pause_sla(
            defect["id"],
            pause_sla_payload(reason="WAITING_ON_REPORTER"),
            team.developer_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_SLA_PAUSE_INVALID_STATUS.value,
        )

    def test_double_pause_rejected(self):
        """PRD §3.8: "Attempting to pause while a pause is already open
        (an SLAPause row exists with ended_at_minute null) is
        ERR_INVALID_SLA_STATE_TRANSITION."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, defect)
        resp = api_client.pause_sla(
            defect["id"],
            pause_sla_payload(reason="WAITING_ON_REPORTER"),
            team.developer_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_SLA_STATE_TRANSITION.value,
        )

    def test_resume_with_no_open_pause_rejected(self):
        """PRD §3.8: "A resume attempt with no open SLAPause row is
        ERR_INVALID_SLA_STATE_TRANSITION."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        resp = api_client.resume_sla(
            defect["id"], team.developer_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_SLA_STATE_TRANSITION.value,
        )

    def test_pause_strict_separation_at_boundary_rejected(self):
        """PRD §3.8: "A new pause may not start at exactly the
        ended_at_minute of the immediately preceding closed pause on the
        same defect — strict separation is required; the rejection code
        is ERR_SLA_PAUSE_ADJACENT. Concretely, if the previous pause
        closed with ended_at_minute equal to X, the next pause may start
        at minute X+1 or later, never at X itself."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, defect)
        advance_clock(team.project, 10)
        resume_sla(team, defect)  # ended_at_minute = 10
        # Now attempt a new pause at exactly clock = 10.
        resp = api_client.pause_sla(
            defect["id"],
            pause_sla_payload(reason="WAITING_ON_REPORTER"),
            team.developer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SLA_PAUSE_ADJACENT.value)

    def test_pause_one_minute_after_resume_succeeds(self):
        """PRD §3.8: "the next pause may start at minute X+1 or later,
        never at X itself."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, defect)
        advance_clock(team.project, 10)
        resume_sla(team, defect)  # ended_at_minute = 10
        advance_clock(team.project, 1)  # clock = 11
        d_after = pause_sla(team, defect)
        assert d_after["sla_state"] == "PAUSED"


class TestSlaPauseAuditTrail:
    def test_pause_appends_sla_pause_audit_entry(self):
        """PRD §3.8: "an AuditEntry of event_type SLA_PAUSE is appended"
        on pause, "an AuditEntry of event_type SLA_RESUME is appended"
        on resume.
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, defect)
        advance_clock(team.project, 5)
        resume_sla(team, defect)
        entries = list_audit_entries(team, defect_id=defect["id"])
        pause_entries = [
            e for e in entries if e["event_type"] == "SLA_PAUSE"
        ]
        resume_entries = [
            e for e in entries if e["event_type"] == "SLA_RESUME"
        ]
        assert len(pause_entries) >= 1
        assert len(resume_entries) >= 1


class TestSlaEscalationSweep:
    def test_escalation_strict_greater_than_at_boundary(self):
        """PRD §3.8: "Boundary semantics are deliberately strict — when
        adjusted-now equals response_due_minute exactly, no breach has
        occurred and the level is not raised."
        """
        team, module, defect = setup_critical_defect_at_clock_zero()
        # CRITICAL+REVENUE_BLOCKING → priority_score 120, multiplier 1.0,
        # response_due_minute = 60.
        assert defect["response_due_minute"] == 60
        advance_clock(team.project, 60)
        run_escalation_sweep(team)
        d_at_boundary = fetch_defect(team, defect["id"])
        assert d_at_boundary["escalation_level"] == 0, (
            "adjusted_now == response_due_minute is NOT a breach"
        )

    def test_escalation_strict_greater_than_one_past_boundary(self):
        """PRD §3.8: "when adjusted-now is strictly greater than
        response_due_minute and the defect's status is in NEW or
        ASSIGNED, the new escalation level is the maximum of the current
        escalation_level and 1".
        """
        team, module, defect = setup_critical_defect_at_clock_zero()
        advance_clock(team.project, 61)  # 1 minute past response_due
        run_escalation_sweep(team)
        d_after = fetch_defect(team, defect["id"])
        assert d_after["escalation_level"] == 1

    def test_escalation_resolution_breach_sets_level_two(self):
        """PRD §3.8: "when adjusted-now is strictly greater than
        resolution_due_minute, the new escalation level is the maximum
        of the current escalation_level and 2".
        """
        team, module, defect = setup_critical_defect_at_clock_zero()
        # CRITICAL+REVENUE_BLOCKING: resolution_due_minute = 0 + ceil(480 * 1.0)
        # = 480. Advance past it.
        advance_clock(team.project, 481)
        run_escalation_sweep(team)
        d_after = fetch_defect(team, defect["id"])
        assert d_after["escalation_level"] == 2

    def test_escalation_frozen_while_paused(self):
        """PRD §3.8: "For each such defect, escalation is frozen when the
        defect is CLOSED or when sla_state is PAUSED — the current
        escalation_level is returned unchanged."
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "ASSIGNED",
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        # response_due_minute = 60 at clock = 0.
        pause_sla(team, defect)
        # Advance well past the response budget while paused.
        advance_clock(team.project, 1000)
        run_escalation_sweep(team)
        d_after = fetch_defect(team, defect["id"])
        assert d_after["escalation_level"] == 0

    def test_escalation_audit_entry_written_on_change(self):
        """PRD §3.8: "Whenever the sweep raises an escalation_level, the
        new value is written to the defect, an AuditEntry of event_type
        ESCALATION is appended with the prior and new levels in
        from_value and to_value".
        """
        team, module, defect = setup_critical_defect_at_clock_zero()
        advance_clock(team.project, 61)
        run_escalation_sweep(team)
        entries = list_audit_entries(
            team, defect_id=defect["id"], event_type="ESCALATION",
        )
        hits = find_audit_entries(entries, from_value="0", to_value="1")
        assert hits, (
            "Expected ESCALATION audit from 0 → 1 after breach"
        )
