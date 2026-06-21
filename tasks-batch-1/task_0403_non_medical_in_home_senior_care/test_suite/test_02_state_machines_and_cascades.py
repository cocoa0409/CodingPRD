"""State-machine cyclicity and cascade depth tests (queue A: Difficulty).

Covers the cyclic visit revert, the claim deny/appeal/resubmit loop, the
caregiver-revoke continuity cascade, and the invoice-dispute claim-deny cascade.
"""
import pytest

from test_helpers import (
    validate_success,
    set_clock, setup_schedulable_scenario,
    create_in_progress_visit, create_completed_visit,
    setup_submitted_claim, get_invoice,
    make_caregiver_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["agency_admin_headers"]
SCHEDULER = TEST_USERS["scheduler_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


class TestVisitCyclicReset:
    """rule_id: non_linear_state_machine / visit_inprogress_reverts_to_scheduled."""

    def test_reset_returns_in_progress_visit_to_scheduled(self, api):
        """PRD §3.6: "Resetting a visit (action of RESET) is permitted from EN_ROUTE or
        IN_PROGRESS, otherwise ERR_INVALID_STATE; it returns the visit to SCHEDULED,
        clears clock_in_at, clock_out_at, and evv_source, and sets billable_minutes and
        visit_charge back to 0, providing the cyclic revert loop for mis-clocked visits."

        Design: Difficulty/non_linear_state_machine/visit_inprogress_reverts_to_scheduled
        """
        s = setup_schedulable_scenario()
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
            "2026-06-01T09:05:00Z")
        reset = validate_success(api.transition_visit(
            v["id"], {"action": "RESET"}, SCHEDULER))
        assert reset["status"] == "SCHEDULED", \
            f"RESET should return visit to SCHEDULED, got {reset['status']}"
        assert reset["clock_in_at"] is None, \
            f"RESET should clear clock_in_at, got {reset['clock_in_at']}"

    def test_reset_clears_billable_minutes(self, api):
        """PRD §3.6: "it returns the visit to SCHEDULED, clears clock_in_at, clock_out_at,
        and evv_source, and sets billable_minutes and visit_charge back to 0, providing
        the cyclic revert loop for mis-clocked visits."

        Design: Difficulty/non_linear_state_machine/visit_inprogress_reverts_to_scheduled
        """
        s = setup_schedulable_scenario()
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        v = create_in_progress_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
            "2026-06-01T09:05:00Z")
        reset = validate_success(api.transition_visit(
            v["id"], {"action": "RESET"}, SCHEDULER))
        assert reset["billable_minutes"] == 0, \
            f"RESET should zero billable_minutes, got {reset['billable_minutes']}"


class TestClaimDeniedAppealedCycle:
    """rule_id: non_linear_state_machine / claim_denied_appealed_resubmitted_cycle."""

    def test_resubmit_after_appeal_returns_to_submitted(self, api):
        """PRD §3.11: "A denied claim can be appealed and resubmitted. Appealing (action
        of APPEAL, DENIED → APPEALED) requires the claim to be DENIED ... Resubmitting an
        appealed claim follows the same submit pathway (APPEALED → SUBMITTED) and requires
        the claim to be APPEALED and the invoice to be ISSUED ... This DENIED → APPEALED →
        SUBMITTED loop is the resubmission cycle."

        Design: Difficulty/non_linear_state_machine/claim_denied_appealed_resubmitted_cycle
        """
        s = setup_submitted_claim(covered_pct=0.50, daily_benefit_max=500, covered_days=5)
        claim = s["claim"]
        validate_success(api.transition_claim(claim["id"], {"action": "DENY"}, ADMIN))
        validate_success(api.transition_claim(claim["id"], {"action": "APPEAL"}, BILLING))
        resubmitted = validate_success(api.submit_claim(claim["id"], BILLING))
        assert resubmitted["status"] == "SUBMITTED", \
            f"resubmit should return claim to SUBMITTED, got {resubmitted['status']}"

    def test_resubmit_recomputes_covered_amount_and_responsibility(self, api):
        """PRD §3.11: "it recomputes the covered_amount by the same smaller-of-percentage-
        or-cap rule, sets the invoice's client_responsible_amount to invoice_total minus
        the recomputed covered_amount rounded half-up to 2 decimal places, and increments
        the invoice's version by one."

        Design: Difficulty/non_linear_state_machine/claim_denied_appealed_resubmitted_cycle
        """
        s = setup_submitted_claim(covered_pct=0.50, daily_benefit_max=500, covered_days=5)
        claim, inv = s["claim"], s["invoice"]
        validate_success(api.transition_claim(claim["id"], {"action": "DENY"}, ADMIN))
        validate_success(api.transition_claim(claim["id"], {"action": "APPEAL"}, BILLING))
        resubmitted = validate_success(api.submit_claim(claim["id"], BILLING))
        # 50% of 240 = 120.00; cap 500*5=2500 -> percentage binds at 120.00.
        assert resubmitted["covered_amount"] == pytest.approx(120.00, abs=0.01), \
            f"recomputed covered_amount should be 120.00, got {resubmitted['covered_amount']}"
        fresh_inv = get_invoice(inv["id"])
        assert fresh_inv["client_responsible_amount"] == pytest.approx(120.00, abs=0.01), \
            f"client_responsible_amount should be 120.00, got {fresh_inv['client_responsible_amount']}"


class TestRevokeCaregiverCascade:
    """rule_id: transitive_cascade / revoke_caregiver_cascades_match_continuity_score."""

    def _setup_revocable(self, api):
        s = setup_schedulable_scenario(target_tier="TIER_2")
        cg, cl, plan = s["caregiver"], s["client"], s["plan"]
        create_completed_visit(
            cg["id"], cl["id"], plan["id"],
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z",
            "2026-06-01T09:00:00Z", "2026-06-01T11:00:00Z")
        return s

    def test_revoke_sets_terminal_dimensions_and_ends_match(self, api):
        """PRD §3.2: "Revocation is terminal on both dimensions at once: background_tier
        becomes REVOKED and employment_status becomes TERMINATED. A wider cascade fires
        here — every match for this caregiver in PROPOSED or ACTIVE has its match_status
        set to ENDED, and again every primary match that held PREFERRED continuity is set
        to BROKEN with the affected client's continuity_score recomputed."

        Design: Difficulty/transitive_cascade/revoke_caregiver_cascades_match_continuity_score
        """
        s = self._setup_revocable(api)
        cg, match = s["caregiver"], s["match"]
        revoked = validate_success(api.transition_caregiver(
            cg["id"], {"action": "REVOKE"}, ADMIN))
        assert revoked["background_tier"] == "REVOKED"
        assert revoked["employment_status"] == "TERMINATED"
        fresh_match = validate_success(api.get_match(match["id"], SCHEDULER))
        assert fresh_match["match_status"] == "ENDED", \
            f"revoke should end the match, got {fresh_match['match_status']}"
        assert fresh_match["continuity_status"] == "BROKEN", \
            f"primary preferred match should become BROKEN, got {fresh_match['continuity_status']}"

    def test_revoke_recomputes_client_continuity_score(self, api):
        """PRD §3.7: "If the client has zero completed visits, the continuity ratio is 0;
        otherwise it is the count of completed visits whose caregiver is the primary
        caregiver divided by the total count of completed visits. ... if the client has no
        active match at all, there is no primary caregiver. ... The final continuity_score
        weights the continuity ratio at 0.6 and reliability at 0.4 ... and rounds the
        result half-up to 2 decimal places."

        Design: Difficulty/transitive_cascade/revoke_caregiver_cascades_match_continuity_score
        """
        s = self._setup_revocable(api)
        cg, cl = s["caregiver"], s["client"]
        validate_success(api.transition_caregiver(cg["id"], {"action": "REVOKE"}, ADMIN))
        fresh_client = validate_success(api.get_client(cl["id"], SCHEDULER))
        # After revoke there is no active match -> no primary -> ratio 0; reliability 1/1.
        # score = 0.6*0 + 0.4*1 = 0.40.
        assert fresh_client["continuity_score"] == pytest.approx(0.40, abs=0.001), \
            f"continuity_score should drop to 0.40, got {fresh_client['continuity_score']}"


class TestDisputeInvoiceCascade:
    """rule_id: transitive_cascade / dispute_invoice_cascades_claim_deny_and_responsibility."""

    def test_dispute_denies_submitted_claim(self, api):
        """PRD §3.10: "Disputing carries a cascade: any claim attached to this invoice
        that is SUBMITTED or APPROVED is moved to DENIED, that denial resets the claim's
        covered_amount to 0, and the invoice's client_responsible_amount is restored to
        its full invoice_total."

        Design: Difficulty/transitive_cascade/dispute_invoice_cascades_claim_deny_and_responsibility
        """
        s = setup_submitted_claim(covered_pct=0.50, daily_benefit_max=500, covered_days=5)
        inv, claim = s["invoice"], s["claim"]
        disputed = validate_success(api.transition_invoice(
            inv["id"], {"action": "DISPUTE"}, ADMIN))
        assert disputed["status"] == "DISPUTED"
        fresh_claim = validate_success(api.get_claim(claim["id"], BILLING))
        assert fresh_claim["status"] == "DENIED", \
            f"dispute should deny the SUBMITTED claim, got {fresh_claim['status']}"
        assert fresh_claim["covered_amount"] == pytest.approx(0, abs=0.01), \
            f"denied claim covered_amount should reset to 0, got {fresh_claim['covered_amount']}"

    def test_dispute_restores_client_responsible_amount(self, api):
        """PRD §3.10: "that denial resets the claim's covered_amount to 0, and the
        invoice's client_responsible_amount is restored to its full invoice_total."

        Design: Difficulty/transitive_cascade/dispute_invoice_cascades_claim_deny_and_responsibility
        """
        s = setup_submitted_claim(covered_pct=0.50, daily_benefit_max=500, covered_days=5)
        inv = s["invoice"]
        disputed = validate_success(api.transition_invoice(
            inv["id"], {"action": "DISPUTE"}, ADMIN))
        # invoice_total 240.00 restored as full client responsibility.
        assert disputed["client_responsible_amount"] == pytest.approx(240.00, abs=0.01), \
            f"client_responsible_amount should restore to 240.00, got {disputed['client_responsible_amount']}"
