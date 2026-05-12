"""Priority score formula tables and SLA-due derivation, including the
age-factor branching across severity tiers.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    advance_clock,
    create_defect,
    effective_resolution_sla,
    effective_response_sla,
    fetch_defect,
    setup_basic_module,
    severity_priority_score,
)


class TestPriorityScoreSeverityWeights:
    @pytest.mark.parametrize("severity,expected_weight", [
        ("BLOCKER", 100),
        ("CRITICAL", 70),
        ("MAJOR", 40),
        ("MINOR", 20),
        ("TRIVIAL", 5),
    ])
    def test_severity_weight_contribution(self, severity, expected_weight):
        """PRD §3.4: "The first is the severity weight: BLOCKER contributes
        100, CRITICAL contributes 70, MAJOR contributes 40, MINOR
        contributes 20, and TRIVIAL contributes 5".
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module, severity=severity, business_impact="UNKNOWN",
        )
        # At clock=0, no reopen, UNKNOWN impact = 0; entire score is the
        # severity weight.
        assert d["priority_score"] == expected_weight


class TestPriorityScoreImpactWeights:
    @pytest.mark.parametrize("impact,expected_impact", [
        ("REVENUE_BLOCKING", 50),
        ("CUSTOMER_FACING", 25),
        ("INTERNAL", 5),
        ("UNKNOWN", 0),
    ])
    def test_business_impact_contribution(self, impact, expected_impact):
        """PRD §3.4: "The second is the business-impact weight:
        REVENUE_BLOCKING contributes 50, CUSTOMER_FACING contributes 25,
        INTERNAL contributes 5, and UNKNOWN contributes 0."
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module, severity="TRIVIAL", business_impact=impact,
        )
        # TRIVIAL weight = 5; total = 5 + impact.
        assert d["priority_score"] == 5 + expected_impact


class TestPriorityScoreAgeFactor:
    def test_age_factor_high_tier_divisor_10(self):
        """PRD §3.4: "when effective_severity is BLOCKER or CRITICAL, the
        age factor is the age-in-minutes divided by 10 using integer
        division (the floor of the quotient), capped at a maximum of 50".
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        # Initial: 70 + 50 + 0 + 0 = 120
        assert d["priority_score"] == 120

        # Advance the clock by 30 minutes. age_factor = 30 // 10 = 3.
        advance_clock(team.project, 30)
        # We need to trigger a recompute. Per PRD §3.4 priority_score is
        # recomputed at the initial report, an approved severity
        # override, a verification-failure reopen, and an SLA-escalation
        # sweep. Run the sweep to fetch a fresh score.
        from test_helpers import run_escalation_sweep
        run_escalation_sweep(team)
        d_after = fetch_defect(team, d["id"])
        assert d_after["priority_score"] == 70 + 50 + 3 + 0 == 123

    def test_age_factor_low_tier_divisor_60(self):
        """PRD §3.4: "for MAJOR, MINOR, or TRIVIAL, the age factor is the
        age-in-minutes divided by 60 using integer division, capped at a
        maximum of 30".
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module, severity="MAJOR", business_impact="INTERNAL",
        )
        # Initial: 40 + 5 + 0 + 0 = 45
        assert d["priority_score"] == 45
        # Advance 120 minutes; age_factor = 120 // 60 = 2.
        advance_clock(team.project, 120)
        from test_helpers import run_escalation_sweep
        run_escalation_sweep(team)
        d_after = fetch_defect(team, d["id"])
        assert d_after["priority_score"] == 40 + 5 + 2 + 0 == 47

    def test_age_factor_cap_high_severity(self):
        """PRD §3.4: "capped at a maximum of 50" (for BLOCKER/CRITICAL).
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="CRITICAL", business_impact="UNKNOWN",
        )
        # Advance 10_000 minutes; would yield 1000 but cap at 50.
        advance_clock(team.project, 10_000)
        from test_helpers import run_escalation_sweep
        run_escalation_sweep(team)
        d_after = fetch_defect(team, d["id"])
        # CRITICAL=70, UNKNOWN=0, age=50, reopen=0 -> 120.
        assert d_after["priority_score"] == 70 + 0 + 50 + 0


class TestSlaDueDerivation:
    def test_response_due_uses_multiplier_relaxed_for_low_score(self):
        """PRD §3.4: "otherwise the multiplier is 1.5 (relaxed track)".
        MAJOR + INTERNAL + age 0 + 0 = 45 (< 80, relaxed track).
        Response base for MAJOR is 240; effective = ceil(240 * 1.5) = 360.
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module, severity="MAJOR", business_impact="INTERNAL",
        )
        assert d["priority_score"] == 45
        assert d["response_due_minute"] == 0 + math.ceil(240 * 1.5)
        assert d["resolution_due_minute"] == 0 + math.ceil(1440 * 1.5)

    def test_response_due_uses_multiplier_standard_at_threshold(self):
        """PRD §3.4: "when priority_score is at least 80 but below 150,
        the multiplier is 1.0 (standard track)". CRITICAL + INTERNAL +
        0 age + 0 reopens = 70 + 5 = 75 (< 80 relaxed!), so make
        CRITICAL+CUSTOMER_FACING: 70+25 = 95 (>= 80, standard).
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="CRITICAL", business_impact="CUSTOMER_FACING",
        )
        assert d["priority_score"] == 95
        # CRITICAL response base = 60; multiplier 1.0 -> 60.
        assert d["response_due_minute"] == 0 + math.ceil(60 * 1.0)

    def test_response_due_uses_multiplier_urgent_at_score_150(self):
        """PRD §3.4: "when priority_score is at least 150, the multiplier
        is 0.5 (urgent track, halving the budget)".
        BLOCKER (100) + REVENUE_BLOCKING (50) = 150 -> urgent track.
        Response base for BLOCKER is 30; effective = ceil(30 * 0.5) = 15.
        """
        team, module = setup_basic_module()
        d = create_defect(
            team, module,
            severity="BLOCKER", business_impact="REVENUE_BLOCKING",
        )
        assert d["priority_score"] == 100 + 50 + 0 + 0 == 150
        # BLOCKER response base = 30, multiplier 0.5 -> ceil(15) = 15.
        assert d["response_due_minute"] == 0 + math.ceil(30 * 0.5) == 15
        assert d["resolution_due_minute"] == 0 + math.ceil(240 * 0.5) == 120


class TestReopenBonus:
    def test_reopen_bonus_adds_fifteen_per_reopen(self):
        """PRD §3.4: "The fourth contribution is the reopen bonus, which
        is 15 multiplied by the current reopen_count — this contribution
        has no cap and accumulates unboundedly across reopen cycles."
        """
        from test_helpers import (
            assign_defect, latest_fix_record, setup_defect_in_state,
            start_progress, submit_fix, verify_defect,
        )

        team, module = setup_basic_module()
        defect = setup_defect_in_state(
            team, module, "FIXED",
            severity="CRITICAL", business_impact="REVENUE_BLOCKING",
        )
        # Round 1: verify(FAILED) → REOPENED, reopen_count = 1.
        verify_defect(team, defect, outcome="FAILED")
        d1 = fetch_defect(team, defect["id"])
        assert d1["reopen_count"] == 1
        expected1 = severity_priority_score(
            "CRITICAL", "REVENUE_BLOCKING",
            age_minutes=0, reopen_count=1,
        )
        assert d1["priority_score"] == expected1
        # Round 2: assign → start → submit-fix → verify(FAILED).
        assign_defect(team, defect)
        start_progress(team, defect)
        submit_fix(team, defect, fix_version="1.0.2")
        verify_defect(team, defect, outcome="FAILED")
        d2 = fetch_defect(team, defect["id"])
        assert d2["reopen_count"] == 2
        expected2 = severity_priority_score(
            "CRITICAL", "REVENUE_BLOCKING",
            age_minutes=0, reopen_count=2,
        )
        assert d2["priority_score"] == expected2 == expected1 + 15
