"""API client: one method per endpoint defined in the PRD (§4 address map)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- funds ---
    def create_fund(self, payload, headers):
        return self._request("POST", "/funds", payload, headers)

    def list_funds(self, headers, params=None):
        return self._request("GET", "/funds", headers=headers, params=params)

    def get_fund(self, fund_id, headers):
        return self._request("GET", f"/funds/{fund_id}", headers=headers)

    def activate_fund(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/activate", {}, headers)

    def close_fund(self, fund_id, headers):
        return self._request("POST", f"/funds/{fund_id}/close", {}, headers)

    # --- agreements ---
    def create_agreement(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/agreements", payload, headers)

    def list_fund_agreements(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def execute_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/execute", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/agreements/{agreement_id}/terminate", {}, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    # --- advisors ---
    def invite_advisor(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/advisors", payload, headers)

    def list_fund_advisors(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/advisors", headers=headers, params=params)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/advisors/{advisor_id}", headers=headers)

    def accept_advisor(self, advisor_id, headers):
        return self._request("POST", f"/advisors/{advisor_id}/accept", {}, headers)

    def resign_advisor(self, advisor_id, headers):
        return self._request("POST", f"/advisors/{advisor_id}/resign", {}, headers)

    def revoke_advisor(self, advisor_id, headers):
        return self._request("POST", f"/advisors/{advisor_id}/revoke", {}, headers)

    def record_advisor_deceased(self, advisor_id, headers):
        return self._request("POST", f"/advisors/{advisor_id}/record-deceased", {}, headers)

    def list_advisors(self, headers, params=None):
        return self._request("GET", "/advisors", headers=headers, params=params)

    # --- contributions & asset lots ---
    def create_contribution(self, payload, headers):
        return self._request("POST", "/contributions", payload, headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/contributions", headers=headers, params=params)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/contributions/{contribution_id}", headers=headers)

    def add_lot(self, contribution_id, payload, headers):
        return self._request("POST", f"/contributions/{contribution_id}/lots", payload, headers)

    def list_contribution_lots(self, contribution_id, headers, params=None):
        return self._request("GET", f"/contributions/{contribution_id}/lots", headers=headers, params=params)

    def accept_contribution(self, contribution_id, headers):
        return self._request("POST", f"/contributions/{contribution_id}/accept", {}, headers)

    def decline_contribution(self, contribution_id, payload, headers):
        return self._request("POST", f"/contributions/{contribution_id}/decline", payload, headers)

    def liquidate_contribution(self, contribution_id, payload, headers):
        return self._request("POST", f"/contributions/{contribution_id}/liquidate", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # --- pools & unitization ---
    def create_pool(self, payload, headers):
        return self._request("POST", "/pools", payload, headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/pools", headers=headers, params=params)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/pools/{pool_id}", headers=headers)

    def suspend_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/suspend", {}, headers)

    def reopen_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/reopen", {}, headers)

    def terminate_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/terminate", {}, headers)

    def create_unitization_event(self, pool_id, payload, headers):
        return self._request("POST", f"/pools/{pool_id}/unitization-events", payload, headers)

    def list_pool_events(self, pool_id, headers, params=None):
        return self._request("GET", f"/pools/{pool_id}/unitization-events", headers=headers, params=params)

    def list_fund_pool_holdings(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/pool-holdings", headers=headers, params=params)

    def get_pool_holding(self, holding_id, headers):
        return self._request("GET", f"/pool-holdings/{holding_id}", headers=headers)

    def list_pool_holdings(self, headers, params=None):
        return self._request("GET", "/pool-holdings", headers=headers, params=params)

    def get_unitization_event(self, event_id, headers):
        return self._request("GET", f"/unitization-events/{event_id}", headers=headers)

    def list_unitization_events(self, headers, params=None):
        return self._request("GET", "/unitization-events", headers=headers, params=params)

    # --- grantees ---
    def create_grantee(self, payload, headers):
        return self._request("POST", "/grantees", payload, headers)

    def list_grantees(self, headers, params=None):
        return self._request("GET", "/grantees", headers=headers, params=params)

    def get_grantee(self, grantee_id, headers):
        return self._request("GET", f"/grantees/{grantee_id}", headers=headers)

    def begin_grantee_review(self, grantee_id, headers):
        return self._request("POST", f"/grantees/{grantee_id}/begin-review", {}, headers)

    def clear_grantee(self, grantee_id, headers):
        return self._request("POST", f"/grantees/{grantee_id}/clear", {}, headers)

    def reject_grantee(self, grantee_id, headers):
        return self._request("POST", f"/grantees/{grantee_id}/reject", {}, headers)

    # --- grant recommendations ---
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def submit_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/submit", {}, headers)

    def claim_grant_review(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/claim-review", {}, headers)

    def approve_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/grants/{grant_id}/approve", payload, headers)

    def return_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/return", {}, headers)

    def deny_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/deny", {}, headers)

    def cancel_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/cancel", {}, headers)

    def disburse_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/disburse", {}, headers)

    def list_grant_disbursements(self, grant_id, headers, params=None):
        return self._request("GET", f"/grants/{grant_id}/disbursements", headers=headers, params=params)

    # --- snapshots / spending runs / fees / statements / disbursements ---
    def create_snapshot(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/market-value-snapshots", payload, headers)

    def list_fund_snapshots(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/market-value-snapshots", headers=headers, params=params)

    def get_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/market-value-snapshots/{snapshot_id}", headers=headers)

    def list_snapshots(self, headers, params=None):
        return self._request("GET", "/market-value-snapshots", headers=headers, params=params)

    def create_spending_run(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/spending-policy-runs", payload, headers)

    def list_fund_spending_runs(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/spending-policy-runs", headers=headers, params=params)

    def get_spending_run(self, run_id, headers):
        return self._request("GET", f"/spending-policy-runs/{run_id}", headers=headers)

    def list_spending_runs(self, headers, params=None):
        return self._request("GET", "/spending-policy-runs", headers=headers, params=params)

    def create_fee_assessment(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/fee-assessments", payload, headers)

    def list_fund_fee_assessments(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/fee-assessments", headers=headers, params=params)

    def get_fee_assessment(self, fee_id, headers):
        return self._request("GET", f"/fee-assessments/{fee_id}", headers=headers)

    def list_fee_assessments(self, headers, params=None):
        return self._request("GET", "/fee-assessments", headers=headers, params=params)

    def create_annual_statement(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/annual-statements", payload, headers)

    def list_fund_annual_statements(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/annual-statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def deliver_statement(self, statement_id, headers):
        return self._request("POST", f"/statements/{statement_id}/deliver", {}, headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def list_fund_disbursements(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    # --- scholarship programs, committees, applications, scores, awards ---
    def create_program(self, fund_id, payload, headers):
        return self._request("POST", f"/funds/{fund_id}/scholarship-programs", payload, headers)

    def list_fund_programs(self, fund_id, headers, params=None):
        return self._request("GET", f"/funds/{fund_id}/scholarship-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/open", {}, headers)

    def close_program_applications(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close-applications", {}, headers)

    def select_winners(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/select-winners", payload, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", {}, headers)

    def cancel_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/cancel", {}, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def seat_committee_member(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/committee-members", payload, headers)

    def list_program_committee_members(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/committee-members", headers=headers, params=params)

    def get_committee_member(self, member_id, headers):
        return self._request("GET", f"/committee-members/{member_id}", headers=headers)

    def list_committee_members(self, headers, params=None):
        return self._request("GET", "/committee-members", headers=headers, params=params)

    def recuse_member(self, member_id, headers):
        return self._request("POST", f"/committee-members/{member_id}/recuse", {}, headers)

    def remove_member(self, member_id, headers):
        return self._request("POST", f"/committee-members/{member_id}/remove", {}, headers)

    def submit_application(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/applications", payload, headers)

    def list_program_applications(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def create_score(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/scores", payload, headers)

    def list_application_scores(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/scores", headers=headers, params=params)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/scores/{score_id}", headers=headers)

    def list_scores(self, headers, params=None):
        return self._request("GET", "/scores", headers=headers, params=params)

    def list_program_awards(self, program_id, headers, params=None):
        return self._request("GET", f"/programs/{program_id}/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def accept_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/accept", {}, headers)

    def decline_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/decline", {}, headers)

    def disburse_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/disburse", {}, headers)

    def forfeit_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/forfeit", {}, headers)


api_client = ApiClient()
