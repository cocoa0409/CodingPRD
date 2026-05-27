"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Plan ─────────────────────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/activate", headers=headers)

    def freeze_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/freeze", headers=headers)

    def unfreeze_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/unfreeze", headers=headers)

    def terminate_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/plans/{plan_id}/terminate", payload, headers)

    # ─── Participant ──────────────────────────────────────────────────
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    def update_deferral_rate(self, participant_id, payload, headers):
        return self._request("PATCH", f"/participants/{participant_id}/deferral-rate", payload, headers)

    def enroll_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/enroll", headers=headers)

    def suspend_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/suspend", headers=headers)

    def resume_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/resume", headers=headers)

    def terminate_participant(self, participant_id, headers):
        return self._request("POST", f"/participants/{participant_id}/terminate", headers=headers)

    # ─── ContributionPeriod ───────────────────────────────────────────
    def create_contribution_period(self, payload, headers):
        return self._request("POST", "/contribution-periods", payload, headers)

    def get_contribution_period(self, cp_id, headers):
        return self._request("GET", f"/contribution-periods/{cp_id}", headers=headers)

    def list_contribution_periods(self, headers, params=None):
        return self._request("GET", "/contribution-periods", headers=headers, params=params)

    def close_contribution_period(self, cp_id, headers):
        return self._request("POST", f"/contribution-periods/{cp_id}/close", headers=headers)

    def reverse_contribution_period(self, cp_id, headers):
        return self._request("POST", f"/contribution-periods/{cp_id}/reverse", headers=headers)

    # ─── Loan ─────────────────────────────────────────────────────────
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def disburse_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/disburse", headers=headers)

    def repay_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/repay", payload, headers)

    def default_loan(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/default", headers=headers)

    # ─── HardshipWithdrawal ───────────────────────────────────────────
    def create_hardship_withdrawal(self, payload, headers):
        return self._request("POST", "/hardship-withdrawals", payload, headers)

    def get_hardship_withdrawal(self, h_id, headers):
        return self._request("GET", f"/hardship-withdrawals/{h_id}", headers=headers)

    def list_hardship_withdrawals(self, headers, params=None):
        return self._request("GET", "/hardship-withdrawals", headers=headers, params=params)

    def approve_hardship(self, h_id, headers):
        return self._request("POST", f"/hardship-withdrawals/{h_id}/approve", headers=headers)

    def deny_hardship(self, h_id, headers):
        return self._request("POST", f"/hardship-withdrawals/{h_id}/deny", headers=headers)

    def pay_hardship(self, h_id, headers):
        return self._request("POST", f"/hardship-withdrawals/{h_id}/pay", headers=headers)

    # ─── RMDDistribution ──────────────────────────────────────────────
    def create_rmd_distribution(self, payload, headers):
        return self._request("POST", "/rmd-distributions", payload, headers)

    def get_rmd_distribution(self, rmd_id, headers):
        return self._request("GET", f"/rmd-distributions/{rmd_id}", headers=headers)

    def list_rmd_distributions(self, headers, params=None):
        return self._request("GET", "/rmd-distributions", headers=headers, params=params)

    def pay_rmd_distribution(self, rmd_id, payload, headers):
        return self._request("POST", f"/rmd-distributions/{rmd_id}/pay", payload, headers)

    def mark_rmd_missed(self, rmd_id, headers):
        return self._request("POST", f"/rmd-distributions/{rmd_id}/mark-missed", headers=headers)

    # ─── VestingEvent ─────────────────────────────────────────────────
    def create_vesting_event(self, payload, headers):
        return self._request("POST", "/vesting-events", payload, headers)

    def get_vesting_event(self, ve_id, headers):
        return self._request("GET", f"/vesting-events/{ve_id}", headers=headers)

    def list_vesting_events(self, headers, params=None):
        return self._request("GET", "/vesting-events", headers=headers, params=params)

    # ─── Test-driving (clock / year-tick) — PRD §3.8 ───────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def year_tick(self, payload, headers):
        return self._request("POST", "/_system/year-tick", payload, headers)


api_client = ApiClient()
