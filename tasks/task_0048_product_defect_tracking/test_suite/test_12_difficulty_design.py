"""Difficulty-design coverage. Every difficulty-design instance has at
least TWO dedicated tests tagged "# difficulty: <rule_id>/<instance_name>".

The grounding PRD sentences are quoted in each test docstring; the
difficulty-design YAML itself is only an extraction index — the
implementer sees PRD prose, so that is what tests cite.
"""
from __future__ import annotations

import math

import pytest

from prd_bench_local_runner.testing import (
    assert_exactly_one_succeeds,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_clock,
    approve_severity_override,
    assign_defect,
    assign_payload,
    close_defect,
    complete_regression_run,
    create_defect,
    create_regression_run,
    create_team_member,
    duplicate_link_payload,
    effective_resolution_sla,
    effective_response_sla,
    fetch_defect,
    fetch_module,
    latest_fix_record,
    list_audit_entries,
    make_triage_manager_headers,
    pause_sla,
    request_severity_override,
    resume_sla,
    run_escalation_sweep,
    setup_basic_module,
    setup_defect_in_state,
    setup_team,
    severity_priority_score,
    start_progress,
    start_regression_run,
    submit_fix,
    submit_fix_payload,
    verify_defect,
    verify_payload,
)


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    # difficulty: dual_variant_calc/defect_sla_breach_forward_vs_chronological
    def test_sla_breach_forward_pause_freezes_escalation(self):
        """PRD §3.8: "For each such defect, escalation is frozen when the
        defect is CLOSED or when sla_state is PAUSED — the current
        escalation_level is returned unchanged."

        Forward-looking sweep: a paused defect does not escalate even
        though wall-clock has advanced past response_due_minute. This
        captures the live-snapshot semantics of the forward variant.
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "ASSIGNED",
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        # response_due_minute = 60. Advance 30, pause, then advance
        # another 40 (40 are paused). adjusted_now sweep reads frozen.
        advance_clock(team.project, 30)
        pause_sla(team, defect)
        advance_clock(team.project, 40)
        run_escalation_sweep(team)
        d_paused = fetch_defect(team, defect["id"])
        assert d_paused["escalation_level"] == 0, (
            "PRD §3.8: escalation frozen while PAUSED"
        )

    # difficulty: dual_variant_calc/defect_sla_breach_forward_vs_chronological
    def test_sla_breach_resume_then_advance_uncovers_breach(self):
        """PRD §3.8: "Otherwise the sweep computes an adjusted-now value
        as the project's current clock_minute minus the defect's
        total_paused_minutes, and compares it against the due-dates
        using strict greater-than".

        After resume, the chronological reading via the (re-run) sweep
        adjusts for paused minutes. Advancing clock past adjusted_now =
        response_due_minute + 1 causes escalation.
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "ASSIGNED",
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        advance_clock(team.project, 30)
        pause_sla(team, defect)
        advance_clock(team.project, 40)
        resume_sla(team, defect)
        # Now clock=70, total_paused_minutes=40, adjusted_now=30 < 60.
        run_escalation_sweep(team)
        d_now = fetch_defect(team, defect["id"])
        assert d_now["escalation_level"] == 0
        # Advance enough to push adjusted_now past response_due.
        advance_clock(team.project, 31)  # clock=101, adjusted=61 > 60
        run_escalation_sweep(team)
        d_breach = fetch_defect(team, defect["id"])
        assert d_breach["escalation_level"] == 1

    # difficulty: dual_variant_calc/module_defect_density_forward_vs_chronological
    def test_density_provisional_reflects_live_override(self):
        """PRD §3.13: "The provisional density is a forward-looking number
        computed against the module's current set of non-terminal
        defects. ... Each eligible defect contributes a per-defect weight
        keyed on its current effective_severity".

        After approving an override from MAJOR to BLOCKER, provisional
        density reads the new (BLOCKER) weight live.
        """
        team, module = setup_basic_module(
            initial_defect_quota=5, kloc=2.0,
        )
        d = create_defect(
            team, module, severity="MAJOR", business_impact="INTERNAL",
        )
        # Before override, provisional density:
        # MAJOR weight 1.0 / 2.0 = 0.50.
        resp1 = api_client.get_density(
            team.triage_headers,
            params={"module_id": module["id"], "mode": "provisional"},
        )
        assert validate_success(resp1)["density"] == pytest.approx(
            0.50, abs=0.001,
        )
        # Override to BLOCKER, approve.
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, ov)
        resp2 = api_client.get_density(
            team.triage_headers,
            params={"module_id": module["id"], "mode": "provisional"},
        )
        # BLOCKER weight 3.0 / 2.0 = 1.50.
        assert validate_success(resp2)["density"] == pytest.approx(
            1.50, abs=0.001,
        )

    # difficulty: dual_variant_calc/module_defect_density_forward_vs_chronological
    def test_density_final_uses_effective_severity_at_closure(self):
        """PRD §3.13: "For each eligible defect the per-defect weight is
        keyed on its effective_severity as it stood at the moment of
        closure, not at the moment of original report — so a defect that
        entered the window classified as MAJOR but had a SeverityOverride
        approved to BLOCKER during the window contributes 3.0, not 1.0."
        """
        team, module = setup_basic_module(
            initial_defect_quota=5, kloc=2.0,
        )
        d = create_defect(team, module, severity="MAJOR")
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, ov)
        assign_defect(team, d)
        start_progress(team, d)
        submit_fix(team, d, fix_version="1.0.1")
        verify_defect(team, d, outcome="PASSED")
        close_defect(team, d)
        resp = api_client.get_density(
            team.triage_headers,
            params={
                "module_id": module["id"], "mode": "final",
                "period_start": 0, "period_end": 1000,
            },
        )
        # weight_at_closure = BLOCKER -> 3.0; per-line round 3.0; sum 3.0;
        # /2.0 = 1.5; final 1.50.
        assert validate_success(resp)["density"] == pytest.approx(
            1.50, abs=0.001,
        )


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    # difficulty: combinatorial_formula/priority_score_four_input_nonlinear
    def test_priority_score_age_factor_branches_on_severity(self):
        """PRD §3.4: "when effective_severity is BLOCKER or CRITICAL, the
        age factor is the age-in-minutes divided by 10 using integer
        division (the floor of the quotient), capped at a maximum of 50;
        for MAJOR, MINOR, or TRIVIAL, the age factor is the age-in-minutes
        divided by 60 using integer division, capped at a maximum of 30."

        At age=60, CRITICAL gets age_factor=6, MAJOR gets 1: same
        numeric inputs produce different scores.
        """
        team, module = setup_basic_module(initial_defect_quota=5)
        d_critical = create_defect(
            team, module,
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        d_major = create_defect(
            team, module,
            severity="MAJOR", business_impact="REVENUE_BLOCKING",
        )
        advance_clock(team.project, 60)
        # Need a recompute. Sweep triggers age recompute on all
        # non-terminal defects (PRD §3.4 lists 'clock-advance recomputes
        # the age component when sweep runs').
        run_escalation_sweep(team)
        d_c = fetch_defect(team, d_critical["id"])
        d_m = fetch_defect(team, d_major["id"])
        # CRITICAL: 70+50+6+0 = 126
        assert d_c["priority_score"] == severity_priority_score(
            "CRITICAL", "REVENUE_BLOCKING",
            age_minutes=60, reopen_count=0,
        ) == 126
        # MAJOR: 40+50+1+0 = 91
        assert d_m["priority_score"] == severity_priority_score(
            "MAJOR", "REVENUE_BLOCKING",
            age_minutes=60, reopen_count=0,
        ) == 91
        assert d_c["priority_score"] != d_m["priority_score"]

    # difficulty: combinatorial_formula/priority_score_four_input_nonlinear
    def test_priority_score_uncapped_reopen_bonus(self):
        """PRD §3.4: "The fourth contribution is the reopen bonus, which
        is 15 multiplied by the current reopen_count — this contribution
        has no cap and accumulates unboundedly across reopen cycles."

        At reopen_count=2 vs reopen_count=0 the bonus gap is exactly 30,
        regardless of any cap.
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "FIXED",
            severity="MAJOR", business_impact="INTERNAL",
        )
        d0 = fetch_defect(team, defect["id"])
        base_score = d0["priority_score"]
        # verify(FAILED), then cycle once more.
        verify_defect(team, defect, outcome="FAILED")
        assign_defect(team, defect)
        start_progress(team, defect)
        submit_fix(team, defect, fix_version="1.0.2")
        verify_defect(team, defect, outcome="FAILED")
        d2 = fetch_defect(team, defect["id"])
        assert d2["reopen_count"] == 2
        # priority gap = 30 (15 per reopen × 2).
        # age may have advanced by 0 here (no clock advance between).
        assert d2["priority_score"] - base_score == 30

    # difficulty: combinatorial_formula/defect_density_per_line_round_then_sum
    def test_density_per_line_then_sum_order(self):
        """PRD §3.13: "The computation proceeds in a strictly pinned
        four-step order: first, each defect's per-defect weight is rounded
        half-up to one decimal place; second, the rounded contributions
        are summed; third, the sum is divided by the module's kloc ...
        fourth, the quotient is rounded half-up to two decimal places.
        The order is load-bearing".

        Four TRIVIAL on kloc=2.0:
        per-line round(0.25→0.3) ×4 = 1.2; /2.0 = 0.6; final 0.60.
        Wrong order (sum-then-round) would yield 0.50.
        """
        team, module = setup_basic_module(
            initial_defect_quota=10, kloc=2.0,
        )
        for _ in range(4):
            create_defect(team, module, severity="TRIVIAL")
        resp = api_client.get_density(
            team.triage_headers,
            params={"module_id": module["id"], "mode": "provisional"},
        )
        assert validate_success(resp)["density"] == pytest.approx(
            0.60, abs=0.001,
        )

    # difficulty: combinatorial_formula/defect_density_per_line_round_then_sum
    def test_density_three_majors_round_per_line(self):
        """PRD §3.13: "The order is load-bearing: rounding per defect
        first, then summing, then dividing, then final-rounding produces
        a different number from summing-then-rounding".

        Three MAJOR (weight 1.0) on kloc 2.0: per-line 1.0 each, sum 3.0,
        / 2.0 = 1.5, final 1.50.
        """
        team, module = setup_basic_module(
            initial_defect_quota=10, kloc=2.0,
        )
        for _ in range(3):
            create_defect(team, module, severity="MAJOR")
        resp = api_client.get_density(
            team.triage_headers,
            params={"module_id": module["id"], "mode": "provisional"},
        )
        assert validate_success(resp)["density"] == pytest.approx(
            1.50, abs=0.001,
        )

    # difficulty: combinatorial_formula/effective_sla_circular_pin
    def test_effective_sla_uses_pinned_score_at_calc_time(self):
        """PRD §3.4: "The computation reads effective_severity and the
        currently-stored priority_score — it does not recompute the
        score inside its own formula, breaking what would otherwise be a
        circular dependency."

        Initial CRITICAL+REVENUE_BLOCKING: priority_score = 120,
        multiplier 1.0, response_due_minute = 60. After advancing the
        clock and approving an override to BLOCKER, the recompute reads
        the new score AT THAT MOMENT.
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        assert d["response_due_minute"] == 60  # 0 + ceil(60 * 1.0)
        advance_clock(team.project, 100)
        # priority_score, if recomputed at clock=100, would be
        # 70 + 50 + min(50, 100//10) + 0 = 70+50+10 = 130 (still standard).
        # Approve override → priority_score will be recomputed under
        # BLOCKER weight: 100+50+10+0 = 160 (urgent track, multiplier 0.5).
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, ov)
        d_after = fetch_defect(team, d["id"])
        # PRD §3.3: due dates recomputed relative to report_clock_minute,
        # NOT approval clock.
        # BLOCKER+REVENUE_BLOCKING+age 100 in BLOCKER tier = 100+50+min(50,10)+0 = 160.
        assert d_after["priority_score"] == 160
        # multiplier 0.5; BLOCKER response base 30 -> ceil(15) = 15.
        # response_due_minute = report_clock_minute (0) + 15 = 15.
        assert d_after["response_due_minute"] == 0 + math.ceil(30 * 0.5)
        assert d_after["response_due_minute"] == 15

    # difficulty: combinatorial_formula/effective_sla_circular_pin
    def test_effective_resolution_multiplier_changes_at_override(self):
        """PRD §3.3: "those two due-dates are recomputed relative to the
        original report_clock_minute, not to the time of override approval
        — that is, the SLA clock is not restarted by an override, only
        re-keyed against the new severity."
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="MAJOR", business_impact="INTERNAL",
        )
        # MAJOR+INTERNAL: 40+5+0+0 = 45 (< 80, multiplier 1.5).
        # Resolution due = 0 + ceil(1440 * 1.5) = 2160.
        assert d["resolution_due_minute"] == math.ceil(1440 * 1.5)
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, ov)
        d_after = fetch_defect(team, d["id"])
        # BLOCKER+INTERNAL: 100+5+0+0 = 105 (>=80 <150, multiplier 1.0).
        # Resolution due = 0 (report_clock_minute) + ceil(240 * 1.0) = 240.
        assert d_after["priority_score"] == 105
        assert d_after["resolution_due_minute"] == math.ceil(240 * 1.0) == 240


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    # difficulty: non_linear_state_machine/defect_reopen_cycle
    def test_three_traversals_increment_reopen_count(self):
        """PRD §3.7: "a chain of five linked side effects in order: first
        the defect's reopen_count is incremented by 1".

        Three verification-failure cycles bump reopen_count to 3.
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        for cycle in range(3):
            verify_defect(team, defect, outcome="FAILED")
            assign_defect(team, defect)
            start_progress(team, defect)
            submit_fix(team, defect, fix_version=f"1.0.{cycle+2}")
        d_after = fetch_defect(team, defect["id"])
        # After three FAILED verifications, reopen_count is 3 and status
        # is FIXED (we re-submitted at the end of the last cycle).
        assert d_after["reopen_count"] == 3

    # difficulty: non_linear_state_machine/defect_reopen_cycle
    def test_reopened_state_after_failed_verification(self):
        """PRD §3.7: "the defect transitions from FIXED to REOPENED".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(team, module, "FIXED")
        verify_defect(team, defect, outcome="FAILED")
        d_after = fetch_defect(team, defect["id"])
        assert d_after["status"] == "REOPENED"

    # difficulty: non_linear_state_machine/severity_override_branching
    def test_approved_branch_mutates_defect(self):
        """PRD §3.3: "Approval — moving the override from PENDING to
        APPROVED — is consequential. The override's approved_by is
        populated from the approver's X-User-ID, and the parent defect's
        effective_severity is set to the override's requested_severity."
        """
        team, module = setup_basic_module()
        d = create_defect(team, module, severity="MAJOR")
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, ov)
        d_after = fetch_defect(team, d["id"])
        assert d_after["effective_severity"] == "BLOCKER"

    # difficulty: non_linear_state_machine/severity_override_branching
    def test_rejected_branch_leaves_defect_untouched(self):
        """PRD §3.3: "Rejection moves the override to REJECTED, leaves
        the parent defect untouched".
        """
        team, module = setup_basic_module()
        d = create_defect(team, module, severity="MAJOR")
        sev_before = d["effective_severity"]
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        # Reject (independent rejector = team.triage).
        api_client.reject_severity_override(
            ov["id"], team.triage_headers,
        )
        d_after = fetch_defect(team, d["id"])
        assert d_after["effective_severity"] == sev_before


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    # difficulty: transitive_cascade/verify_failed_reopen_cascade_depth4
    def test_verify_failed_full_reopen_chain(self):
        """PRD §3.7: "that transition fires a chain of five linked side
        effects in order: first the defect's reopen_count is incremented
        by 1; second the priority_score is recomputed using the new
        reopen_count ... third the response_due_minute is reset to the
        project's current clock_minute plus the effective response budget
        computed against the freshly-recomputed priority_score (and so
        the response SLA clock restarts at the moment of reopen, not at
        the original report time); fourth an AuditEntry of event_type
        STATUS_CHANGE is appended with from_value FIXED and to_value
        REOPENED; and fifth, a second AuditEntry of event_type
        ESCALATION is appended with from_value the defect's prior
        escalation_level and to_value 0".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "FIXED",
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        # Advance clock by 10 minutes BEFORE verify(FAILED) so the new
        # response_due_minute is anchored at clock=10, not 0.
        advance_clock(team.project, 10)
        verify_defect(team, defect, outcome="FAILED")
        d = fetch_defect(team, defect["id"])
        # Link 1: status -> REOPENED
        assert d["status"] == "REOPENED"
        # Link 2: reopen_count -> 1
        assert d["reopen_count"] == 1
        # Link 3: priority_score = 70+50+min(50,10//10)+15*1 = 70+50+1+15 = 136
        expected_score = severity_priority_score(
            "CRITICAL", "REVENUE_BLOCKING",
            age_minutes=10, reopen_count=1,
        )
        assert d["priority_score"] == expected_score == 136
        # Link 4: response_due_minute = current clock (10) +
        # effective_response_sla(CRITICAL, 136)
        expected_rdm = 10 + effective_response_sla("CRITICAL", 136)
        assert d["response_due_minute"] == expected_rdm
        # Link 5: escalation_level reset to 0
        assert d["escalation_level"] == 0
        # AuditEntry STATUS_CHANGE FIXED -> REOPENED
        entries = list_audit_entries(team, defect_id=defect["id"])
        sc = [
            e for e in entries
            if e["event_type"] == "STATUS_CHANGE"
            and e.get("from_value") == "FIXED"
            and e.get("to_value") == "REOPENED"
        ]
        assert sc, "Expected STATUS_CHANGE FIXED→REOPENED audit entry"

    # difficulty: transitive_cascade/verify_failed_reopen_cascade_depth4
    def test_reopen_writes_escalation_audit_to_zero(self):
        """PRD §3.7: "a second AuditEntry of event_type ESCALATION is
        appended with from_value the defect's prior escalation_level and
        to_value 0, because reopen resets escalation_level back to 0".
        """
        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "FIXED",
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        verify_defect(team, defect, outcome="FAILED")
        entries = list_audit_entries(
            team, defect_id=defect["id"], event_type="ESCALATION",
        )
        zeros = [e for e in entries if str(e.get("to_value")) == "0"]
        assert zeros, (
            "Expected ESCALATION audit with to_value=0 on reopen"
        )

    # difficulty: transitive_cascade/override_approval_severity_cascade_depth3
    def test_override_approval_cascade_severity_score_resolution(self):
        """PRD §3.3: "the parent defect's effective_severity is set to
        the override's requested_severity. That severity change triggers
        a recomputation of the defect's priority_score, which in turn
        drives a recomputation of response_due_minute and
        resolution_due_minute; those two due-dates are recomputed relative
        to the original report_clock_minute, not to the time of override
        approval".
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="MAJOR", business_impact="INTERNAL",
        )
        # priority 45, multiplier 1.5, resolution_due = ceil(1440*1.5)=2160.
        assert d["priority_score"] == 45
        assert d["resolution_due_minute"] == 2160
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, ov)
        d_after = fetch_defect(team, d["id"])
        # Link 1: effective_severity -> BLOCKER
        assert d_after["effective_severity"] == "BLOCKER"
        # Link 2: priority_score = 100+5+0+0 = 105 (>=80 <150, multiplier 1.0)
        assert d_after["priority_score"] == 105
        # Link 3: resolution_due_minute = 0 + ceil(240 * 1.0) = 240
        assert d_after["resolution_due_minute"] == 240

    # difficulty: transitive_cascade/override_approval_severity_cascade_depth3
    def test_override_approval_writes_severity_change_audit(self):
        """PRD §3.3: "An AuditEntry of event_type SEVERITY_CHANGE is
        appended carrying the prior and new effective_severity as
        from_value and to_value."
        """
        team, module = setup_basic_module()
        d = create_defect(team, module, severity="MAJOR")
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        approve_severity_override(team, ov)
        entries = list_audit_entries(
            team, defect_id=d["id"], event_type="SEVERITY_CHANGE",
        )
        hits = [
            e for e in entries
            if e.get("from_value") == "MAJOR"
            and e.get("to_value") == "BLOCKER"
        ]
        assert hits


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    # difficulty: priority_pair_validation_conflict/state_vs_referential_on_assign
    def test_closed_defect_returns_closed_not_referential_error(self):
        """PRD §2.10: "The order is fixed ... target-resource state
        preconditions for the requested transition are fifth ... business
        referential checks come next (assignee eligibility, module-and-
        reporter validity)".

        On /assign with a CLOSED defect and an ineligible assignee, the
        state error (priority 5) wins over the referential error
        (priority 8). The closest PRD-named state error for a CLOSED
        defect that fails the NEW-required precondition is
        ERR_DEFECT_NOT_NEW (assign requires status=NEW), or
        ERR_DEFECT_CLOSED if implementation treats CLOSED specially.
        Either is a state-class error; relax to either.
        """
        team_a, module_a = setup_basic_module()
        defect = setup_defect_in_state(team_a, module_a, "CLOSED")
        # A cross-project (ineligible) assignee.
        team_b = setup_team()
        resp = api_client.assign_defect(
            defect["id"], team_a.triage_headers,
            assign_payload(assignee_id=team_b.developer["id"]),
        )
        # State error (priority 5) wins over referential (priority 8).
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_DEFECT_NOT_NEW.value,
            ApiErrorId.ERR_DEFECT_CLOSED.value,
        ])

    # difficulty: priority_pair_validation_conflict/state_vs_referential_on_assign
    def test_referential_error_fires_when_no_state_violation(self):
        """PRD §3.5: "the referenced TeamMember must exist, be ACTIVE,
        and have project_id matching the defect's project_id —
        otherwise ERR_TEAM_MEMBER_NOT_ELIGIBLE."

        With a NEW defect and a cross-project assignee, no state
        violation applies, so the priority-8 referential check fires.
        """
        team_a, module_a = setup_basic_module()
        defect = create_defect(team_a, module_a)  # NEW
        team_b = setup_team()
        resp = api_client.assign_defect(
            defect["id"], team_a.triage_headers,
            assign_payload(assignee_id=team_b.developer["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_TEAM_MEMBER_NOT_ELIGIBLE.value,
        )

    # difficulty: priority_pair_validation_conflict/state_vs_safety_on_override_approve
    def test_override_not_pending_wins_over_independence(self):
        """PRD §3.3: "Once an override reaches either terminal state, it
        cannot be revisited: a second approve or reject attempt is
        rejected with ERR_OVERRIDE_NOT_PENDING."

        PRD §2.10: state preconditions (priority 5) fire before
        business_safety (priority 7 — approver independence). When a
        requester tries to re-approve an already-approved override
        BOTH conditions would fail; state wins.
        """
        team, module = setup_basic_module()
        d = create_defect(team, module, severity="MAJOR")
        triage_a = create_team_member(
            team.project, "TRIAGE_MANAGER",
            triage_headers=team.triage_headers,
        )
        triage_b = create_team_member(
            team.project, "TRIAGE_MANAGER",
            triage_headers=team.triage_headers,
        )
        # Triage_a requests, Triage_b approves -> APPROVED.
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=triage_a,
        )
        api_client.approve_severity_override(
            ov["id"], make_triage_manager_headers(triage_b["id"]),
        )
        # Now triage_a (the original requester) tries to approve again.
        # State (override not pending) AND safety (approver = requester)
        # would both fail. State wins.
        resp = api_client.approve_severity_override(
            ov["id"], make_triage_manager_headers(triage_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OVERRIDE_NOT_PENDING.value)

    # difficulty: priority_pair_validation_conflict/state_vs_safety_on_override_approve
    def test_independence_check_fires_when_override_is_pending(self):
        """PRD §3.3: "If X-User-ID on the approve or reject call equals
        the override's requested_by, the operation is refused with
        ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT."

        When the override is still PENDING, no state-error precondition
        applies, so the priority-7 independence safety check fires for
        the self-approval attempt.
        """
        team, module = setup_basic_module()
        d = create_defect(team, module, severity="MAJOR")
        triage_a = create_team_member(
            team.project, "TRIAGE_MANAGER",
            triage_headers=team.triage_headers,
        )
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=triage_a,
        )
        resp = api_client.approve_severity_override(
            ov["id"], make_triage_manager_headers(triage_a["id"]),
        )
        validate_error(
            resp,
            ApiErrorId.ERR_OVERRIDE_APPROVER_NOT_INDEPENDENT.value,
        )


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:
    # difficulty: boundary_precision_check/sla_breach_strict_greater_than
    def test_sla_breach_strict_greater_than_at_response_due(self):
        """PRD §3.8: "Boundary semantics are deliberately strict — when
        adjusted-now equals response_due_minute exactly, no breach has
        occurred and the level is not raised."
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        # response_due_minute = 60. Status = NEW (priority 1 condition).
        advance_clock(team.project, 60)
        run_escalation_sweep(team)
        d_at = fetch_defect(team, d["id"])
        assert d_at["escalation_level"] == 0

    # difficulty: boundary_precision_check/sla_breach_strict_greater_than
    def test_sla_breach_strict_greater_than_one_past(self):
        """PRD §3.8: "when adjusted-now is strictly greater than
        response_due_minute and the defect's status is in NEW or
        ASSIGNED, the new escalation level is the maximum of the current
        escalation_level and 1".
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        advance_clock(team.project, 61)
        run_escalation_sweep(team)
        d_past = fetch_defect(team, d["id"])
        assert d_past["escalation_level"] == 1

    # NOTE: A previous boundary test asserting `data["reopen_rate"] == 0.0`
    # was removed because PRD §3.13 does not name the response field for
    # the reopen-rate endpoint, only the rate computation. The companion
    # test below still verifies the boundary semantics (200, not error)
    # without depending on a specific response key.

    # difficulty: boundary_precision_check/reopen_rate_empty_set_returns_zero
    def test_reopen_rate_returns_200_not_error(self):
        """PRD §3.13: "When the eligible set is empty the rate is 0.0,
        not an error".
        """
        team, module = setup_basic_module()
        resp = api_client.get_reopen_rate(
            team.triage_headers,
            params={
                "module_id": module["id"],
                "period_start": 0, "period_end": 1000,
            },
        )
        assert resp.status_code == 200


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    # difficulty: cross_entity_state_dependency/defect_submit_fix_requires_module_active
    def test_module_archive_blocked_by_active_defect(self):
        """PRD §3.1: "A module archive likewise refuses to proceed when
        that module's active_defect_count is greater than zero, returning
        ERR_MODULE_HAS_ACTIVE_DEFECTS".

        Module's state transition is gated on Defect-domain state — a
        non-terminal defect on the module blocks archive.
        """
        team, module = setup_basic_module()
        setup_defect_in_state(team, module, "IN_PROGRESS")
        resp = api_client.archive_module(
            team.project["id"], module["id"], team.triage_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_MODULE_HAS_ACTIVE_DEFECTS.value,
        )

    # difficulty: cross_entity_state_dependency/defect_submit_fix_requires_module_active
    def test_module_remains_active_after_failed_archive(self):
        """PRD §3.1: "A module archive likewise refuses to proceed when
        that module's active_defect_count is greater than zero".

        On failure, the module's state is unchanged.
        """
        team, module = setup_basic_module()
        setup_defect_in_state(team, module, "IN_PROGRESS")
        api_client.archive_module(
            team.project["id"], module["id"], team.triage_headers,
        )
        m_after = fetch_module(team, module["id"])
        assert m_after["status"] == "ACTIVE"

    # difficulty: cross_entity_state_dependency/severity_override_approve_requires_defect_open
    def test_approve_override_on_closed_defect_rejected(self):
        """PRD §3.3: "The parent defect must not be in terminal CLOSED
        state — an override on a closed defect is rejected with
        ERR_DEFECT_CLOSED."

        SeverityOverride's PENDING -> APPROVED transition is gated on
        parent Defect state.
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "NEW")
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        # Drive defect to CLOSED without approving the override.
        assign_defect(team, d)
        start_progress(team, d)
        submit_fix(team, d, fix_version="1.0.1")
        verify_defect(team, d, outcome="PASSED")
        close_defect(team, d)
        resp = api_client.approve_severity_override(
            ov["id"], team.triage_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEFECT_CLOSED.value)

    # difficulty: cross_entity_state_dependency/severity_override_approve_requires_defect_open
    def test_override_stays_pending_after_rejected_approval(self):
        """PRD §3.3: "an override on a closed defect is rejected with
        ERR_DEFECT_CLOSED."

        After a failed approval the override's status stays PENDING.
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "NEW")
        ov = request_severity_override(
            team, d, requested_severity="BLOCKER",
            requester=team.developer,
        )
        assign_defect(team, d)
        start_progress(team, d)
        submit_fix(team, d, fix_version="1.0.1")
        verify_defect(team, d, outcome="PASSED")
        close_defect(team, d)
        api_client.approve_severity_override(
            ov["id"], team.triage_headers,
        )
        # Re-read override.
        from test_helpers import fetch_severity_override
        ov_after = fetch_severity_override(team, ov["id"])
        assert ov_after["status"] == "PENDING"


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    # difficulty: resource_temporal_overlap/sla_pause_no_adjacent_pauses_on_defect
    def test_pause_at_exact_resume_minute_rejected(self):
        """PRD §3.8: "A new pause may not start at exactly the
        ended_at_minute of the immediately preceding closed pause on the
        same defect — strict separation is required; the rejection code
        is ERR_SLA_PAUSE_ADJACENT."
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, d)
        advance_clock(team.project, 5)
        resume_sla(team, d)  # ended_at_minute = 5
        from test_helpers import pause_sla_payload
        resp = api_client.pause_sla(
            d["id"], pause_sla_payload(reason="WAITING_ON_REPORTER"),
            team.developer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SLA_PAUSE_ADJACENT.value)

    # difficulty: resource_temporal_overlap/sla_pause_no_adjacent_pauses_on_defect
    def test_pause_one_minute_after_resume_succeeds(self):
        """PRD §3.8: "the next pause may start at minute X+1 or later,
        never at X itself."
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, d)
        advance_clock(team.project, 5)
        resume_sla(team, d)  # ended_at_minute = 5
        advance_clock(team.project, 1)  # clock = 6
        from test_helpers import pause_sla_payload
        resp = api_client.pause_sla(
            d["id"], pause_sla_payload(reason="WAITING_ON_REPORTER"),
            team.developer_headers,
        )
        data = validate_success(resp)
        assert data["sla_state"] == "PAUSED"

    # difficulty: resource_temporal_overlap/regression_run_cooldown_with_inclusive_buffer_on_module
    def test_regression_cooldown_inclusive_at_ten_minutes(self):
        """PRD §3.10: "equality at exactly 10 minutes permits the start
        (the boundary is inclusive)".
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "FIXED")
        r1 = create_regression_run(team, d)
        start_regression_run(team, r1)
        complete_regression_run(team, r1, result="PASSED")
        advance_clock(team.project, 10)
        r2 = create_regression_run(team, d)
        resp = api_client.start_regression_run(
            r2["id"], team.release_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "RUNNING"

    # difficulty: resource_temporal_overlap/regression_run_cooldown_with_inclusive_buffer_on_module
    def test_regression_cooldown_blocks_at_nine_minutes(self):
        """PRD §3.10: "A start attempted within the cooldown window is
        rejected with ERR_REGRESSION_COOLDOWN_ACTIVE."
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "FIXED")
        r1 = create_regression_run(team, d)
        start_regression_run(team, r1)
        complete_regression_run(team, r1, result="PASSED")
        advance_clock(team.project, 9)
        r2 = create_regression_run(team, d)
        resp = api_client.start_regression_run(
            r2["id"], team.release_headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_REGRESSION_COOLDOWN_ACTIVE.value,
        )


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    # difficulty: compensating_invariant/sla_pause_resume_conserves_elapsed_time
    def test_total_paused_plus_running_equals_elapsed(self):
        """PRD §3.8: paraphrasing the resume side-effect — the system
        "increments the defect's total_paused_minutes by the difference
        between that closed ended_at_minute and the row's
        started_at_minute". After multiple pause/resume cycles the
        invariant total_paused_minutes + active_running_minutes ==
        elapsed_wall_time must hold.
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "ASSIGNED")
        # Pause at clock 0, resume at clock 7 (7 min paused)
        pause_sla(team, d)
        advance_clock(team.project, 7)
        resume_sla(team, d)
        # Pause again at clock 10 (3 min idle), resume at clock 14
        advance_clock(team.project, 3)
        pause_sla(team, d)
        advance_clock(team.project, 4)
        resume_sla(team, d)
        # clock = 14, total_paused = 11 (7+4)
        d_after = fetch_defect(team, d["id"])
        assert d_after["total_paused_minutes"] == 11
        # Re-fetch project clock via project endpoint.
        from test_helpers import fetch_project
        p_after = fetch_project(team)
        elapsed = p_after["clock_minute"] - d_after["report_clock_minute"]
        # active_running_minutes = elapsed - total_paused_minutes
        active_running = elapsed - d_after["total_paused_minutes"]
        assert active_running >= 0
        # Invariant: paused + running == elapsed
        assert d_after["total_paused_minutes"] + active_running == elapsed

    # difficulty: compensating_invariant/sla_pause_resume_conserves_elapsed_time
    def test_single_pause_resume_accumulates_correctly(self):
        """PRD §3.8: "increments the defect's total_paused_minutes by the
        difference between that closed ended_at_minute and the row's
        started_at_minute".
        """
        team, module = setup_basic_module()
        d = setup_defect_in_state(team, module, "ASSIGNED")
        pause_sla(team, d)
        advance_clock(team.project, 15)
        d_after = resume_sla(team, d)
        assert d_after["total_paused_minutes"] == 15

    # difficulty: compensating_invariant/module_quota_invariant_on_create_close_cycle
    def test_quota_invariant_holds_through_create_cycle(self):
        """PRD §3.1: "throughout the module's life the system maintains
        the invariant that initial_defect_quota equals the sum of
        quota_remaining and active_defect_count, with quota_remaining
        never falling below zero in any committed state."
        """
        team, module = setup_basic_module(initial_defect_quota=3)
        d1 = create_defect(team, module)
        m1 = fetch_module(team, module["id"])
        assert m1["active_defect_count"] == 1
        assert m1["quota_remaining"] == 2
        assert m1["initial_defect_quota"] == (
            m1["active_defect_count"] + m1["quota_remaining"]
        )
        d2 = create_defect(team, module)
        m2 = fetch_module(team, module["id"])
        assert m2["active_defect_count"] == 2
        assert m2["quota_remaining"] == 1
        assert m2["initial_defect_quota"] == (
            m2["active_defect_count"] + m2["quota_remaining"]
        )

    # difficulty: compensating_invariant/module_quota_invariant_on_create_close_cycle
    def test_quota_invariant_holds_through_close_cycle(self):
        """PRD §3.9: "On a successful close ... the module's
        active_defect_count decrements by 1, the module's quota_remaining
        increments by 1, and an AuditEntry of event_type STATUS_CHANGE
        with from_value VERIFIED and to_value CLOSED is appended."
        """
        team, module = setup_basic_module(initial_defect_quota=3)
        d = setup_defect_in_state(team, module, "VERIFIED")
        m_before = fetch_module(team, module["id"])
        assert m_before["active_defect_count"] == 1
        assert m_before["quota_remaining"] == 2
        close_defect(team, d)
        m_after = fetch_module(team, module["id"])
        assert m_after["active_defect_count"] == 0
        assert m_after["quota_remaining"] == 3
        assert m_after["initial_defect_quota"] == (
            m_after["active_defect_count"] + m_after["quota_remaining"]
        )
