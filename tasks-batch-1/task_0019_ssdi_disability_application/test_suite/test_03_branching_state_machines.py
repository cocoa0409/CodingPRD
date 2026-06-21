"""Branching state machines: Application MEDICAL_REVIEW fork → reconsideration
loop → ALJ; ChildAuxiliaryBenefit age vs parent fork."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    set_clock, advance_clock,
    setup_application_in_medical_review,
    setup_application_awarded,
    setup_awarded_with_active_child,
    setup_hearing_in_requested,
    submit_medical_decision,
    request_reconsideration, request_hearing,
    schedule_hearing, record_hearing_held, decide_hearing,
    create_child_auxiliary, get_current_award,
    suspend_award,
    make_claimant_headers,
)


# =========================================================================
# Instance: application_branching_medical_decision_fork
# =========================================================================

class TestApplicationBranchingMedicalDecisionFork:
    """The medical-decision endpoint branches into APPROVED_INITIAL vs
    DENIED_MEDICAL, and the denial path opens a revision loop through
    RECONSIDERATION → ALJ_PENDING → ALJ_APPROVED that creates a different
    back_pay_variant than the initial branch."""

    def test_denial_then_reconsideration_then_alj_approves_creates_alj_variant_award(self, api):
        """PRD §3.4: "If the decision is `NOT_DISABLED`, the server records
        the decision row, sets the application's `medical_decision` to
        `NOT_DISABLED`, transitions the application from `MEDICAL_REVIEW`
        to `DENIED_MEDICAL`, and increments the application's `version`."
        PRD §3.5: "An `APPROVED` outcome propagates upward: the application
        transitions from `ALJ_PENDING` through `ALJ_APPROVED`, its
        `medical_decision` is set to `RFC_DISABLED`, a `BenefitAward` is
        created (with `back_pay_variant` of `ALJ_APPROVAL` — see §3.6 for
        the variant difference)"

        Design: Difficulty/non_linear_state_machine/application_branching_medical_decision_fork
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "2020",
                "full_name": "Loop Claimant",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        set_clock("2026-05-01T00:00:00Z")
        schedule_hearing(hearing["id"], "2027-12-01T00:00:00Z")
        set_clock("2027-12-15T00:00:00Z")
        # PRD §3.5: decision transitions from SCHEDULED to APPROVED/DENIED.
        # record-held is purely administrative and is NOT a precondition for decision.
        decide_hearing(hearing["id"], "APPROVED")
        # Verify the application reached ALJ_APPROVED (or AWARDED via cascade).
        app_id = ctx["application"]["id"]
        res = api_client.get_application(app_id, TEST_USERS["ssa_admin_headers"])
        app = get_success_data(res)
        assert app["status"] in {"ALJ_APPROVED", "AWARDED"}, \
            f"Expected ALJ_APPROVED or AWARDED, got {app['status']}"
        # The cascade created a BenefitAward with ALJ_APPROVAL variant.
        res = api_client.list_awards(TEST_USERS["benefits_admin_headers"],
                                      params={"application_id": app_id})
        awards = get_success_data(res)
        assert len(awards) == 1
        assert awards[0]["back_pay_variant"] == "ALJ_APPROVAL"

    def test_denied_medical_transitions_application_status(self, api):
        """PRD §3.4: "If the decision is `NOT_DISABLED`, the server records
        the decision row, sets the application's `medical_decision` to
        `NOT_DISABLED`, transitions the application from `MEDICAL_REVIEW`
        to `DENIED_MEDICAL`, and increments the application's `version`."

        Design: Difficulty/non_linear_state_machine/application_branching_medical_decision_fork
        """
        set_clock("2026-01-15T00:00:00Z")
        claimant, app = setup_application_in_medical_review(
            claimant_overrides={
                "ssn_last4": "2021",
                "full_name": "Branch Denial",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        v_before = app["version"]
        submit_medical_decision(
            app["id"],
            expected_application_version=v_before,
            decision_type="NOT_DISABLED",
            established_onset_date="2024-01-15T00:00:00Z",
        )
        res = api_client.get_application(app["id"], TEST_USERS["ssa_admin_headers"])
        app_after = get_success_data(res)
        assert app_after["status"] == "DENIED_MEDICAL"
        assert app_after["medical_decision"] == "NOT_DISABLED"
        assert app_after["version"] > v_before, \
            "Application.version must increment after medical decision"


# =========================================================================
# Instance: child_auxiliary_branching_termination_age_vs_parent
# =========================================================================

class TestChildAuxiliaryBranchingTerminationAgeVsParent:
    """One child crosses age 18 (TERMINATED_AGE), another loses parent's
    award via suspend (TERMINATED_PARENT) — same starting state, two
    different triggers, two different terminal statuses."""

    def test_age_advance_terminates_overage_child_only(self, api):
        """PRD §3.8: "A child who reaches or passes age 18 is automatically
        moved to `TERMINATED_AGE`: when the server clock is advanced (via
        the test-driving capability described in §2.10), the system
        iterates every still-`ACTIVE` auxiliary and terminates any whose
        child-age (the difference between the new server time and
        `child_date_of_birth`) is at least 18 years."

        Design: Difficulty/non_linear_state_machine/child_auxiliary_branching_termination_age_vs_parent
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "3030",
                "full_name": "Parent C",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            medical_clock_override="2026-03-15T00:00:00Z",
        )
        award = ctx["award"]
        # Child A turns 18 on 2026-04-01; Child B is much younger.
        child_a = create_child_auxiliary(
            award["id"],
            expected_benefit_award_version=award["version"],
            child_full_name="Child A",
            child_date_of_birth="2008-04-01T00:00:00Z",
        )
        award_after_a = get_current_award(award["id"])
        child_b = create_child_auxiliary(
            award["id"],
            expected_benefit_award_version=award_after_a["version"],
            child_full_name="Child B",
            child_date_of_birth="2015-01-01T00:00:00Z",
        )
        # Advance clock past Child A's 18th birthday.
        advance_clock("2026-05-01T00:00:00Z")
        # Child A → TERMINATED_AGE.
        res_a = api_client.list_child_auxiliaries(
            award["id"], TEST_USERS["benefits_admin_headers"]
        )
        children = get_success_data(res_a)
        children_by_id = {c["id"]: c for c in children}
        assert children_by_id[child_a["id"]]["status"] == "TERMINATED_AGE", \
            f"Expected TERMINATED_AGE for over-18 child, got {children_by_id[child_a['id']]['status']}"
        # Child B remains ACTIVE.
        assert children_by_id[child_b["id"]]["status"] == "ACTIVE"

    def test_award_suspension_terminates_remaining_active_child_with_parent_status(self, api):
        """PRD §3.8: "A `BenefitsAdmin` who suspends an `ACTIVE` award
        transitions that award to `SUSPENDED` and, in the same logical
        step, sets every still-`ACTIVE` `ChildAuxiliaryBenefit` attached to
        that award to `TERMINATED_PARENT`, refreshing those auxiliaries'
        `updated_at` and incrementing the award's `version`."

        Design: Difficulty/non_linear_state_machine/child_auxiliary_branching_termination_age_vs_parent
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_awarded_with_active_child(
            claimant_overrides={
                "ssn_last4": "3031",
                "full_name": "Sus Parent",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            child_full_name="Suspended Child",
            child_date_of_birth="2015-01-01T00:00:00Z",
        )
        award = ctx["award"]
        child = ctx["child"]
        suspend_award(award["id"])
        # Child status → TERMINATED_PARENT.
        res = api_client.list_child_auxiliaries(
            award["id"], TEST_USERS["benefits_admin_headers"]
        )
        children = get_success_data(res)
        children_by_id = {c["id"]: c for c in children}
        assert children_by_id[child["id"]]["status"] == "TERMINATED_PARENT", \
            f"Expected TERMINATED_PARENT after award suspend, got {children_by_id[child['id']]['status']}"
