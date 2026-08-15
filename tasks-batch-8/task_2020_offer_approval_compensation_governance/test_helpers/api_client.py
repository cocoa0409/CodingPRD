"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Requisition ---
    def create_requisition(self, payload, headers):
        return self._request("POST", "/api/requisitions", payload, headers)

    def list_requisitions(self, headers, params=None):
        return self._request("GET", "/api/requisitions", headers=headers, params=params)

    def get_requisition(self, requisition_id, headers):
        return self._request("GET", f"/api/requisitions/{requisition_id}", headers=headers)

    def patch_requisition(self, requisition_id, payload, headers):
        return self._request("PATCH", f"/api/requisitions/{requisition_id}", payload, headers)

    def submit_requisition(self, requisition_id, headers):
        return self._request("POST", f"/api/requisitions/{requisition_id}/submit", {}, headers)

    def review_decision_requisition(self, requisition_id, payload, headers):
        return self._request("POST", f"/api/requisitions/{requisition_id}/review-decision", payload, headers)

    def hold_requisition(self, requisition_id, payload, headers):
        return self._request("POST", f"/api/requisitions/{requisition_id}/hold", payload, headers)

    def cancel_requisition(self, requisition_id, payload, headers):
        return self._request("POST", f"/api/requisitions/{requisition_id}/cancel", payload, headers)

    # --- Candidate ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/api/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/api/candidates/{candidate_id}", headers=headers)

    def archive_candidate(self, candidate_id, headers):
        return self._request("POST", f"/api/candidates/{candidate_id}/archive", {}, headers)

    # --- InternalEquitySnapshot ---
    def create_equity_snapshot(self, payload, headers):
        return self._request("POST", "/api/equity-snapshots", payload, headers)

    def list_equity_snapshots(self, headers, params=None):
        return self._request("GET", "/api/equity-snapshots", headers=headers, params=params)

    def get_equity_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/api/equity-snapshots/{snapshot_id}", headers=headers)

    # --- ApprovalPolicy ---
    def create_approval_policy(self, payload, headers):
        return self._request("POST", "/api/approval-policies", payload, headers)

    def list_approval_policies(self, headers, params=None):
        return self._request("GET", "/api/approval-policies", headers=headers, params=params)

    def deactivate_approval_policy(self, policy_id, headers):
        return self._request("POST", f"/api/approval-policies/{policy_id}/deactivate", {}, headers)

    # --- Offer ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/api/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/api/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}", headers=headers)

    def patch_offer(self, offer_id, payload, headers):
        return self._request("PATCH", f"/api/offers/{offer_id}", payload, headers)

    def submit_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/submit", {}, headers)

    def withdraw_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/withdraw", payload, headers)

    def extend_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/extend", {}, headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/accept", {}, headers)

    def decline_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/decline", payload, headers)

    def rescind_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/rescind", payload, headers)

    # --- ApprovalStep ---
    def list_approval_steps(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}/approval-steps", headers=headers)

    def decide_approval_step(self, step_id, payload, headers):
        return self._request("POST", f"/api/approval-steps/{step_id}/decide", payload, headers)

    # --- NegotiationRound ---
    def create_negotiation_round(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/negotiation-rounds", payload, headers)

    def list_negotiation_rounds(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}/negotiation-rounds", headers=headers)

    def decide_negotiation_round(self, round_id, payload, headers):
        return self._request("POST", f"/api/negotiation-rounds/{round_id}/decision", payload, headers)

    # --- PerkPackage ---
    def create_perk(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/perks", payload, headers)

    def list_perks(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}/perks", headers=headers)

    def get_clawback_quote(self, perk_id, headers, months_worked):
        return self._request(
            "GET", f"/api/perks/{perk_id}/clawback-quote",
            headers=headers, params={"months_worked": months_worked},
        )

    # --- ClearanceCheck ---
    def create_clearance_check(self, offer_id, payload, headers):
        return self._request("POST", f"/api/offers/{offer_id}/clearance-checks", payload, headers)

    def list_clearance_checks(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}/clearance-checks", headers=headers)

    def transition_clearance_check(self, check_id, payload, headers):
        return self._request("POST", f"/api/clearance-checks/{check_id}/transition", payload, headers)

    def waive_clearance_check(self, check_id, payload, headers):
        return self._request("POST", f"/api/clearance-checks/{check_id}/waive", payload, headers)

    # --- OfferLetter ---
    def create_offer_letter(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/letters", {}, headers)

    def list_offer_letters(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}/letters", headers=headers)

    # --- OfferEvent ---
    def list_offer_events(self, offer_id, headers, params=None):
        return self._request("GET", f"/api/offers/{offer_id}/events", headers=headers, params=params)

    # --- DelegationGrant ---
    def create_delegation_grant(self, payload, headers):
        return self._request("POST", "/api/delegation-grants", payload, headers)

    def list_delegation_grants(self, headers, params=None):
        return self._request("GET", "/api/delegation-grants", headers=headers, params=params)

    def get_delegation_grant(self, grant_id, headers):
        return self._request("GET", f"/api/delegation-grants/{grant_id}", headers=headers)

    def revoke_delegation_grant(self, grant_id, headers):
        return self._request("POST", f"/api/delegation-grants/{grant_id}/revoke", {}, headers)


api_client = ApiClient()
