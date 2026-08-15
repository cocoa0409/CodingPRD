"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/pre-award/_clock/set_current_utc", payload, headers)

    # --- Funding opportunities ---
    def create_funding_opportunity(self, payload, headers):
        return self._request("POST", "/pre-award/funding-opportunities", payload, headers)

    def get_funding_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/pre-award/funding-opportunities/{opportunity_id}", headers=headers)

    # --- Principal investigators ---
    def create_principal_investigator(self, payload, headers):
        return self._request("POST", "/pre-award/principal-investigators", payload, headers)

    def get_principal_investigator(self, pi_id, headers):
        return self._request("GET", f"/pre-award/principal-investigators/{pi_id}", headers=headers)

    # --- F&A rate agreements ---
    def create_fa_rate_agreement(self, payload, headers):
        return self._request("POST", "/pre-award/fa-rate-agreements", payload, headers)

    def finalize_fa_rate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/pre-award/fa-rate-agreements/{agreement_id}/finalize", headers=headers)

    def get_fa_rate_agreement(self, agreement_id, headers):
        return self._request("GET", f"/pre-award/fa-rate-agreements/{agreement_id}", headers=headers)

    # --- Subrecipient orgs ---
    def create_subrecipient_org(self, payload, headers):
        return self._request("POST", "/pre-award/subrecipient-orgs", payload, headers)

    def get_subrecipient_org(self, org_id, headers):
        return self._request("GET", f"/pre-award/subrecipient-orgs/{org_id}", headers=headers)

    def list_org_subrecipient_commitments(self, org_id, headers):
        return self._request("GET", f"/pre-award/subrecipient-orgs/{org_id}/subrecipient-commitments", headers=headers)

    # --- Proposals ---
    def create_proposal(self, payload, headers):
        return self._request("POST", "/pre-award/proposals", payload, headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/pre-award/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}", headers=headers)

    def patch_proposal(self, proposal_id, payload, headers):
        return self._request("PATCH", f"/pre-award/proposals/{proposal_id}", payload, headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/withdraw", headers=headers)

    # --- Budget lines ---
    def create_budget_line(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/budget-lines", payload, headers)

    def list_proposal_budget_lines(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/budget-lines", headers=headers)

    def get_budget_line(self, line_id, headers):
        return self._request("GET", f"/pre-award/budget-lines/{line_id}", headers=headers)

    def list_budget_lines(self, headers, params=None):
        return self._request("GET", "/pre-award/budget-lines", headers=headers, params=params)

    def delete_budget_line(self, line_id, headers):
        return self._request("DELETE", f"/pre-award/budget-lines/{line_id}", headers=headers)

    # --- Budget finalization / snapshots ---
    def create_budget_finalization(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/budget-finalizations", payload, headers)

    def list_budget_snapshots(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/budget-snapshots", headers=headers)

    # --- Routing & institutional decision ---
    def route_proposal(self, proposal_id, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/route", headers=headers)

    def approve_institutional(self, proposal_id, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/approve-institutional", headers=headers)

    def return_for_revision(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/return-for-revision", payload, headers)

    # --- Submission portal ---
    def submit_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/submit", payload, headers)

    def list_submission_packages(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/submission-packages", headers=headers)

    # --- JIT ---
    def create_jit_notice(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/jit-notices", payload, headers)

    def create_jit_response(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/jit-responses", payload, headers)

    # --- Cost share ---
    def create_cost_share_commitment(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/cost-share-commitments", payload, headers)

    def list_cost_share_commitments(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/cost-share-commitments", headers=headers)

    def approve_cost_share_commitment(self, commitment_id, headers):
        return self._request("POST", f"/pre-award/cost-share-commitments/{commitment_id}/approve", headers=headers)

    def release_cost_share_commitment(self, commitment_id, headers):
        return self._request("POST", f"/pre-award/cost-share-commitments/{commitment_id}/release", headers=headers)

    def withdraw_cost_share_commitment(self, commitment_id, headers):
        return self._request("POST", f"/pre-award/cost-share-commitments/{commitment_id}/withdraw", headers=headers)

    # --- Compliance reviews ---
    def create_compliance_review(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/compliance-reviews", payload, headers)

    def list_compliance_reviews(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/compliance-reviews", headers=headers)

    def request_review_info(self, review_id, payload, headers):
        return self._request("POST", f"/pre-award/compliance-reviews/{review_id}/request-info", payload, headers)

    def respond_to_review(self, review_id, payload, headers):
        return self._request("POST", f"/pre-award/compliance-reviews/{review_id}/respond", payload, headers)

    def approve_review(self, review_id, payload, headers):
        return self._request("POST", f"/pre-award/compliance-reviews/{review_id}/approve", payload, headers)

    def disapprove_review(self, review_id, payload, headers):
        return self._request("POST", f"/pre-award/compliance-reviews/{review_id}/disapprove", payload, headers)

    # --- Subrecipient commitments ---
    def create_subrecipient_commitment(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/subrecipient-commitments", payload, headers)

    def list_subrecipient_commitments(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/subrecipient-commitments", headers=headers)

    def verify_subrecipient_commitment(self, commitment_id, headers):
        return self._request("POST", f"/pre-award/subrecipient-commitments/{commitment_id}/verify", headers=headers)

    def void_subrecipient_commitment(self, commitment_id, headers):
        return self._request("POST", f"/pre-award/subrecipient-commitments/{commitment_id}/void", headers=headers)

    # --- Negotiation offers ---
    def create_negotiation_offer(self, proposal_id, payload, headers):
        return self._request("POST", f"/pre-award/proposals/{proposal_id}/negotiation-offers", payload, headers)

    def list_negotiation_offers(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/negotiation-offers", headers=headers)

    def accept_negotiation_offer(self, offer_id, headers):
        return self._request("POST", f"/pre-award/negotiation-offers/{offer_id}/accept", headers=headers)

    def decline_negotiation_offer(self, offer_id, headers):
        return self._request("POST", f"/pre-award/negotiation-offers/{offer_id}/decline", headers=headers)

    # --- Award handoff ---
    def list_award_handoffs(self, proposal_id, headers):
        return self._request("GET", f"/pre-award/proposals/{proposal_id}/award-handoffs", headers=headers)

    def mark_handoff_ready(self, handoff_id, headers):
        return self._request("POST", f"/pre-award/award-handoffs/{handoff_id}/mark-ready", headers=headers)

    def complete_handoff(self, handoff_id, headers):
        return self._request("POST", f"/pre-award/award-handoffs/{handoff_id}/handoff", headers=headers)


api_client = ApiClient()
