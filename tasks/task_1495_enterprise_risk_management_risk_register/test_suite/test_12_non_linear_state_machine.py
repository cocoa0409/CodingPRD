"""Difficulty: non_linear_state_machine — Risk reassessment/reopen cycles and
KRI parallel lifecycle/breach dimensions. Two instances x two tests each."""
import pytest

from test_helpers import (
    api_client,
    validate_success, get_success_data,
    create_category, create_risk, create_residual_assessed_risk,
    create_approved_plan, cancel_plan,
    create_active_kri, observe_kri, get_kri, advance_clock,
    get_risk, get_risk_version,
    make_risk_owner_headers, make_risk_manager_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER,
)


class TestRiskReassessmentAndReopenCycles:
    """Instance: risk_reassessment_and_reopen_cycles — the Risk machine is
    cyclic: MONITORING → REASSESSMENT → MONITORING loop via reassess +
    INHERENT re-assessment, and CLOSED → IDENTIFIED reopen."""

    def _build_monitoring_risk(self):
        """Drive a risk to MONITORING via: ASSESSED (inherent+residual) →
        plan approved → enter-treatment → plan cancelled → monitor."""
        cat = create_category(name="Cyc")
        risk = create_residual_assessed_risk(
            category_id=cat["id"], likelihood=3, impact=3,
            treatment_budget_cents=100_000,
        )
        plan = create_approved_plan(risk["id"], budget_cents=50_000)
        api_client.enter_treatment(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        cancel_plan(plan["id"])
        api_client.monitor_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        return risk

    def test_reassess_then_inherent_returns_to_monitoring(self):
        """PRD §3.2: "Sending a `MONITORING` risk to `REASSESSMENT` is
        unconditional — the reassessment loop exists so a watched risk can be
        re-scored whenever conditions change, returning it to `MONITORING`
        through the inherent assessment described above."

        Design: Difficulty/non_linear_state_machine/risk_reassessment_and_reopen_cycles
        """
        risk = self._build_monitoring_risk()
        api_client.reassess_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        mid = get_risk(risk["id"])
        assert mid["status"] == "REASSESSMENT"
        # INHERENT assessment from REASSESSMENT moves the risk to MONITORING
        v = get_risk_version(risk["id"])
        api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 2, "impact": 2,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        after = get_risk(risk["id"])
        assert after["status"] == "MONITORING"
        assert after["inherent_score"] == 4
        # No ACTIVE mappings — residual recomputes to inherent base
        assert after["residual_score"] == 4

    def test_close_then_reopen_returns_to_identified_preserving_scores(self):
        """PRD §3.2: "A `CLOSED` risk can be reopened to `IDENTIFIED` without
        preconditions; an optional `reason` may accompany the reopening, and
        the risk's scores, control mappings, and `kri_alert` are all
        preserved as the lifecycle resumes at `IDENTIFIED`."

        Design: Difficulty/non_linear_state_machine/risk_reassessment_and_reopen_cycles
        """
        risk = self._build_monitoring_risk()
        # Drive through the loop: REASSESSMENT → INHERENT → MONITORING
        api_client.reassess_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        v = get_risk_version(risk["id"])
        api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 2, "impact": 2,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        # Close from MONITORING (no open breaches, no non-terminal plans)
        api_client.close_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        closed = get_risk(risk["id"])
        assert closed["status"] == "CLOSED"
        # Reopen → IDENTIFIED with scores preserved
        api_client.reopen_risk(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
            payload={"reason": "regulator inquiry"},
        )
        after = get_risk(risk["id"])
        assert after["status"] == "IDENTIFIED"
        assert after["inherent_score"] == 4


class TestKriParallelLifecycleAndBreachDimensions:
    """Instance: kri_parallel_lifecycle_and_breach_dimensions — KRI carries
    two parallel state dimensions: lifecycle (linear) and breach (cyclic)."""

    def _build_active_kri(self):
        cat = create_category(name="ParK")
        kri = create_active_kri(
            cat["id"], name="Liquidity ratio", direction="ABOVE",
            amber_threshold=50, red_threshold=75,
            min_observation_interval_days=0,
        )
        # Observation timestamps below lie after the default logical clock
        # (2026-08-01T00:00:00Z); advance it first so they are not rejected
        # as future observations (PRD §3.6 ERR_OBSERVATION_IN_FUTURE).
        advance_clock("2026-08-02T00:00:00Z")
        return kri

    def test_breach_dimension_cycles_amber_red_normal(self):
        """PRD §3.6: "The breach dimension, `current_breach_status`, is
        cyclic across `NORMAL`, `AMBER_BREACH`, and `RED_BREACH`, starts at
        `NORMAL`, and is driven solely by observations — it may change only
        while the indicator is `ACTIVE`".

        Design: Difficulty/non_linear_state_machine/kri_parallel_lifecycle_and_breach_dimensions
        """
        kri = self._build_active_kri()
        o1 = observe_kri(kri["id"], 51, "2026-08-01T01:00:00Z")
        assert o1["resulting_breach_status"] == "AMBER_BREACH"
        o2 = observe_kri(kri["id"], 76, "2026-08-01T02:00:00Z")
        assert o2["resulting_breach_status"] == "RED_BREACH"
        o3 = observe_kri(kri["id"], 10, "2026-08-01T03:00:00Z")
        assert o3["resulting_breach_status"] == "NORMAL"
        # Lifecycle stayed ACTIVE through all three observations
        kri_after = get_kri(kri["id"])
        assert kri_after["status"] == "ACTIVE"

    def test_retire_freezes_breach_dimension(self):
        """PRD §3.6: "retirement freezes it at its last value."

        Design: Difficulty/non_linear_state_machine/kri_parallel_lifecycle_and_breach_dimensions
        """
        kri = self._build_active_kri()
        observe_kri(kri["id"], 51, "2026-08-01T01:00:00Z")
        observe_kri(kri["id"], 76, "2026-08-01T02:00:00Z")
        observe_kri(kri["id"], 10, "2026-08-01T03:00:00Z")
        api_client.retire_kri(
            kri["id"], make_risk_manager_headers(USER_RISK_MANAGER),
        )
        kri_after = get_kri(kri["id"])
        assert kri_after["status"] == "RETIRED"
        # Frozen at the last evaluated value (NORMAL)
        assert kri_after["current_breach_status"] == "NORMAL"
