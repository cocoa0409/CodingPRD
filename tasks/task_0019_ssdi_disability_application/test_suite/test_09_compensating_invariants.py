"""Compensating-action invariants: hearing request → cancel round-trip;
award suspend → reinstate PIA conservation."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    set_clock,
    setup_hearing_in_requested,
    setup_awarded_with_active_child,
    suspend_award, reinstate_award,
    make_claimant_headers,
)


# =========================================================================
# Instance: hearing_cancel_invariant_application_state_round_trip
# =========================================================================

class TestHearingCancelInvariantApplicationStateRoundTrip:
    """Application.status must return to RECONSIDERATION after the
    request-hearing + cancel round-trip, and no non-CANCELLED HearingRequest
    remains for the application."""

    def test_application_status_returns_to_reconsideration_after_cancel(self, api):
        """PRD §3.5: "A claimant who changes their mind before the hearing
        is scheduled may cancel a `REQUESTED` hearing; the cancellation
        moves the hearing to `CANCELLED`, reverts the parent application
        from `ALJ_PENDING` to `RECONSIDERATION` so that the claimant
        retains the option to re-request, and increments the hearing's
        `version`."

        Design: Difficulty/compensating_invariant/hearing_cancel_invariant_application_state_round_trip
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "5555",
                "full_name": "Round Trip",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        claimant = ctx["claimant"]
        app_id = ctx["application"]["id"]
        # Cancel the requested hearing.
        res = api_client.cancel_hearing(hearing["id"], make_claimant_headers(claimant["id"]))
        get_success_data(res)
        # Application back to RECONSIDERATION.
        res = api_client.get_application(app_id, TEST_USERS["ssa_admin_headers"])
        app_after = get_success_data(res)
        assert app_after["status"] == "RECONSIDERATION"

    def test_only_cancelled_hearings_remain_for_application(self, api):
        """PRD §3.5: "A claimant who changes their mind before the hearing
        is scheduled may cancel a `REQUESTED` hearing; the cancellation
        moves the hearing to `CANCELLED`"

        Design: Difficulty/compensating_invariant/hearing_cancel_invariant_application_state_round_trip
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "5556",
                "full_name": "Hear Only Cancel",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        app_id = ctx["application"]["id"]
        res = api_client.cancel_hearing(hearing["id"], make_claimant_headers(ctx["claimant"]["id"]))
        get_success_data(res)
        # Every hearing associated with this application should be CANCELLED.
        res = api_client.list_hearings(TEST_USERS["alj_headers"],
                                       params={"application_id": app_id})
        items = get_success_data(res)
        assert len(items) >= 1
        non_cancelled = [h for h in items if h["status"] != "CANCELLED"]
        assert non_cancelled == [], \
            f"Expected no non-CANCELLED hearings for {app_id}, found {non_cancelled}"


# =========================================================================
# Instance: award_suspend_reinstate_invariant_pia_unchanged
# =========================================================================

class TestAwardSuspendReinstateInvariantPiaUnchanged:
    """The award's PIA and monthly_benefit are conserved across a suspend
    → reinstate cycle; the cascaded child termination is asymmetric (by
    PRD design) and is not auto-reinstated."""

    def test_pia_and_monthly_benefit_unchanged_after_suspend_reinstate(self, api):
        """PRD §3.8: "Reinstating a `SUSPENDED` award transitions it back
        to `ACTIVE` and increments its `version`, but — by design — does
        not auto-reinstate the previously terminated auxiliaries: each
        terminated auxiliary must be re-created if the household wants
        the dependent benefit back."
        PRD §3.6: "The award's `monthly_benefit_cents` equals the computed
        PIA — for a primary insured the monthly cash benefit is the PIA
        itself."

        Design: Difficulty/compensating_invariant/award_suspend_reinstate_invariant_pia_unchanged
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_awarded_with_active_child(
            claimant_overrides={
                "ssn_last4": "6666",
                "full_name": "Sus Re",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            child_full_name="Reinst Child",
            child_date_of_birth="2015-01-01T00:00:00Z",
        )
        award = ctx["award"]
        pia_before = award["primary_insurance_amount_cents"]
        mb_before = award["monthly_benefit_cents"]
        # Suspend, then reinstate.
        suspend_award(award["id"])
        reinstated = reinstate_award(award["id"])
        assert reinstated["status"] == "ACTIVE"
        # PIA and monthly_benefit conserved.
        assert reinstated["primary_insurance_amount_cents"] == pia_before, \
            f"PIA must be conserved through suspend/reinstate; was {pia_before}, now {reinstated['primary_insurance_amount_cents']}"
        assert reinstated["monthly_benefit_cents"] == mb_before
        # Per PRD §3.6: PIA = 196_092 for the 12-yr 4.8M earnings baseline.
        assert reinstated["primary_insurance_amount_cents"] == 196_092
        assert reinstated["monthly_benefit_cents"] == 196_092

    def test_child_remains_terminated_after_reinstate(self, api):
        """PRD §3.8: "Reinstating a `SUSPENDED` award transitions it back
        to `ACTIVE` and increments its `version`, but — by design — does
        not auto-reinstate the previously terminated auxiliaries: each
        terminated auxiliary must be re-created if the household wants
        the dependent benefit back."

        Design: Difficulty/compensating_invariant/award_suspend_reinstate_invariant_pia_unchanged
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_awarded_with_active_child(
            claimant_overrides={
                "ssn_last4": "6667",
                "full_name": "Child Asym",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            child_full_name="Asym Child",
            child_date_of_birth="2015-01-01T00:00:00Z",
        )
        award = ctx["award"]
        child = ctx["child"]
        suspend_award(award["id"])
        reinstate_award(award["id"])
        # Child should still be TERMINATED_PARENT (asymmetric by design).
        res = api_client.list_child_auxiliaries(award["id"], TEST_USERS["benefits_admin_headers"])
        children = get_success_data(res)
        by_id = {c["id"]: c for c in children}
        assert by_id[child["id"]]["status"] == "TERMINATED_PARENT", \
            "Reinstating the award must not auto-reinstate the child auxiliary"
