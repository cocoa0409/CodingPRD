"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Clients ──────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def deposit_wallet(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/wallet/deposit", payload, headers)

    def list_client_job_postings(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/job-postings", headers=headers, params=params)

    def list_client_contracts(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/contracts", headers=headers, params=params)

    # ─── Freelancers ──────────────────────────────────────────────────
    def create_freelancer(self, payload, headers):
        return self._request("POST", "/freelancers", payload, headers)

    def list_freelancers(self, headers, params=None):
        return self._request("GET", "/freelancers", headers=headers, params=params)

    def get_freelancer(self, freelancer_id, headers):
        return self._request("GET", f"/freelancers/{freelancer_id}", headers=headers)

    def update_freelancer(self, freelancer_id, payload, headers):
        return self._request("PATCH", f"/freelancers/{freelancer_id}", payload, headers)

    def list_freelancer_proposals(self, freelancer_id, headers, params=None):
        return self._request("GET", f"/freelancers/{freelancer_id}/proposals", headers=headers, params=params)

    def list_freelancer_contracts(self, freelancer_id, headers, params=None):
        return self._request("GET", f"/freelancers/{freelancer_id}/contracts", headers=headers, params=params)

    def list_freelancer_payouts(self, freelancer_id, headers, params=None):
        return self._request("GET", f"/freelancers/{freelancer_id}/payouts", headers=headers, params=params)

    def list_freelancer_tax_records(self, freelancer_id, headers, params=None):
        return self._request("GET", f"/freelancers/{freelancer_id}/tax-records", headers=headers, params=params)

    # ─── Job Postings ─────────────────────────────────────────────────
    def create_job_posting(self, payload, headers):
        return self._request("POST", "/job-postings", payload, headers)

    def list_job_postings(self, headers, params=None):
        return self._request("GET", "/job-postings", headers=headers, params=params)

    def get_job_posting(self, posting_id, headers):
        return self._request("GET", f"/job-postings/{posting_id}", headers=headers)

    def cancel_job_posting(self, posting_id, headers):
        return self._request("POST", f"/job-postings/{posting_id}/cancel", headers=headers)

    def list_posting_proposals(self, posting_id, headers, params=None):
        return self._request("GET", f"/job-postings/{posting_id}/proposals", headers=headers, params=params)

    def ranked_proposals(self, posting_id, headers, params=None):
        return self._request("GET", f"/job-postings/{posting_id}/ranked-proposals", headers=headers, params=params)

    # ─── Proposals ────────────────────────────────────────────────────
    def create_proposal(self, payload, headers):
        return self._request("POST", "/proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def counter_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/counter", payload, headers)

    def accept_proposal(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/accept", payload, headers)

    def decline_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/decline", headers=headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/withdraw", headers=headers)

    # ─── Contracts ────────────────────────────────────────────────────
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", payload, headers)

    def complete_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/complete", headers=headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", headers=headers)

    def list_contract_milestones(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/milestones", headers=headers, params=params)

    def list_contract_timelogs(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/timelogs", headers=headers, params=params)

    def list_contract_escrow(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/escrow-transactions", headers=headers, params=params)

    def list_contract_disputes(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/disputes", headers=headers, params=params)

    def list_contract_reviews(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/reviews", headers=headers, params=params)

    # ─── Milestones (contract-scoped) ─────────────────────────────────
    def create_milestone(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/milestones", payload, headers)

    def get_milestone_in_contract(self, contract_id, milestone_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/milestones/{milestone_id}", headers=headers)

    def fund_milestone(self, contract_id, milestone_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/milestones/{milestone_id}/fund", payload, headers)

    def submit_milestone(self, contract_id, milestone_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/milestones/{milestone_id}/submit-work", headers=headers)

    def approve_milestone(self, contract_id, milestone_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/milestones/{milestone_id}/approve", headers=headers)

    def release_milestone(self, contract_id, milestone_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/milestones/{milestone_id}/release", payload, headers)

    def dispute_milestone(self, contract_id, milestone_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/milestones/{milestone_id}/dispute", payload, headers)

    # ─── TimeLogs ─────────────────────────────────────────────────────
    def create_timelog(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/timelogs", payload, headers)

    def verify_timelog(self, contract_id, timelog_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/timelogs/{timelog_id}/verify", headers=headers)

    def reject_timelog(self, contract_id, timelog_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/timelogs/{timelog_id}/reject", headers=headers)

    # ─── Disputes ─────────────────────────────────────────────────────
    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def assign_arbitration(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/assign-arbitration", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", payload, headers)

    # ─── Payouts ──────────────────────────────────────────────────────
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def settle_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/settle", headers=headers)

    # ─── Milestones (global) ──────────────────────────────────────────
    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/milestones/{milestone_id}", headers=headers)

    def list_milestone_payouts(self, milestone_id, headers, params=None):
        return self._request("GET", f"/milestones/{milestone_id}/payouts", headers=headers, params=params)

    def list_milestone_escrow(self, milestone_id, headers, params=None):
        return self._request("GET", f"/milestones/{milestone_id}/escrow-transactions", headers=headers, params=params)

    def list_milestone_timelogs(self, milestone_id, headers, params=None):
        return self._request("GET", f"/milestones/{milestone_id}/timelogs", headers=headers, params=params)

    def list_milestone_disputes(self, milestone_id, headers, params=None):
        return self._request("GET", f"/milestones/{milestone_id}/disputes", headers=headers, params=params)

    # ─── Reviews ──────────────────────────────────────────────────────
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    # ─── Tax Records ──────────────────────────────────────────────────
    def create_tax_record(self, payload, headers):
        return self._request("POST", "/tax-records", payload, headers)

    def get_tax_record(self, record_id, headers):
        return self._request("GET", f"/tax-records/{record_id}", headers=headers)


api_client = ApiClient()
