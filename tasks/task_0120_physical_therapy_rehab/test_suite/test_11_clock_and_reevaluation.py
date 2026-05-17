"""Simulated clock advance and the four time-gated sweeps: REEVAL_DUE,
plan EXPIRED, authorization EXPIRED, VeteranReferral EXPIRED.

PRD §3.10 / §3.6.
"""
from __future__ import annotations

from test_helpers import (
    REEVAL_DUE_DAYS,
    TEST_USERS,
    advance_clock_days,
    anchor_clock,
    create_evaluation,
    finalize_evaluation,
    iso_anchor_offset,
    iso_date_anchor_offset,
    make_therapist_headers,
    re_get_episode,
    setup_active_episode,
    setup_reeval_due_episode,
    validate_success,
)


# ===========================================================================
# Reeval sweep — Difficulty design Rule 3.
# ===========================================================================
class TestReevalSweep:

    def test_active_to_reeval_due_on_30_day_gap(self, api):
        """PRD §3.6: "When the test clock is advanced and the gap
        reaches 30 days or more on an ACTIVE episode, the episode is
        swept to REEVAL_DUE."

        Claim: clock advance to day 31 from anchor → Episode.status
        == REEVAL_DUE.
        """
        setup = setup_active_episode()
        ep_pre = setup["episode"]
        assert ep_pre["status"] == "ACTIVE"
        advance_clock_days(REEVAL_DUE_DAYS + 1)
        ep_post = re_get_episode(ep_pre["id"])
        assert ep_post["status"] == "REEVAL_DUE"

    def test_episode_reeval_cycle_branching(self, api):
        """# difficulty: non_linear_state_machine/episode_reeval_cycle_branching
        PRD §3.6: "The therapist clears the block by creating a new
        Evaluation whose evaluation_type is REEVAL and finalizing it;
        the finalize cascade then moves the episode from REEVAL_DUE
        back to ACTIVE."

        Claim: ACTIVE → REEVAL_DUE (via clock) → ACTIVE (via REEVAL
        finalize).
        """
        setup = setup_reeval_due_episode()
        therapist = setup["therapist"]
        ep_due = setup["episode"]
        assert ep_due["status"] == "REEVAL_DUE"
        # Create REEVAL Evaluation.
        reeval = create_evaluation(
            episode_id=ep_due["id"], evaluation_type="REEVAL",
            clinician_id=therapist["id"], complexity="LOW",
            functional_baseline_score=70,
            acting_therapist_id=therapist["id"],
        )
        finalize_evaluation(
            evaluation_id=reeval["id"],
            acting_therapist_id=therapist["id"],
        )
        ep_after = re_get_episode(ep_due["id"])
        assert ep_after["status"] == "ACTIVE"

    def test_reeval_due_creates_branching_outcome_to_discharge_pending(
            self, api):
        """# difficulty: non_linear_state_machine/episode_reeval_cycle_branching
        PRD §3.9: "On a successful create, the assessment is created
        in DRAFT and the episode is moved from ACTIVE (or from
        REEVAL_DUE) to DISCHARGE_PENDING."

        Claim: in REEVAL_DUE, creating a DischargeAssessment branches
        the episode to DISCHARGE_PENDING (distinct from the
        cycle-back-to-ACTIVE path).
        """
        from test_helpers import (
            create_discharge_assessment, create_dpt_therapist,
        )
        setup = setup_reeval_due_episode()
        # PRD §3.9: requires no SCHEDULED/IN_SESSION visits. The
        # reeval-due fixture does not create any visits.
        discharger = create_dpt_therapist()
        discharge = create_discharge_assessment(
            episode_id=setup["episode"]["id"],
            discharging_clinician_id=discharger["id"],
            acting_therapist_id=discharger["id"],
            discharge_outcome="GOALS_MET",
            final_functional_score=80,
        )
        ep = re_get_episode(setup["episode"]["id"])
        assert ep["status"] == "DISCHARGE_PENDING"
        assert discharge["status"] == "DRAFT"


# ===========================================================================
# Plan expiry sweep — PRD §3.10 / §3.3.
# ===========================================================================
class TestPlanExpirySweep:

    def test_active_plan_expires_when_clock_passes_cert_end(self, api):
        """PRD §3.10: "every ACTIVE plan of care whose cert_period_end
        has been crossed is moved to terminal EXPIRED."
        PRD §3.3: "Plans whose cert_period_end is passed by the
        system clock are swept from ACTIVE to EXPIRED, with their
        SCHEDULED visits cancelled."

        Claim: advance clock past cert_period_end → PlanOfCare.status
        == EXPIRED.
        """
        setup = setup_active_episode(cert_period_days=10)
        plan_id = setup["plan_of_care"]["id"]
        advance_clock_days(11)
        # Re-fetch the plan.
        res = api.get_plan_of_care(
            plan_id, TEST_USERS["clinic_admin_headers"],
        )
        plan = validate_success(res, expected_status=200)
        assert plan["status"] == "EXPIRED"
