"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/v1/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/v1/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/plans/{plan_id}", headers=headers)

    def terminate_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/terminate", {}, headers)

    # --- Actuaries ---
    def create_actuary(self, payload, headers):
        return self._request("POST", "/v1/actuaries", payload, headers)

    def get_actuary(self, actuary_id, headers):
        return self._request("GET", f"/v1/actuaries/{actuary_id}", headers=headers)

    # --- Census batches ---
    def create_census_batch(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/census-batches", payload, headers)

    def list_census_batches(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/census-batches", headers=headers, params=params)

    def get_census_batch(self, batch_id, headers):
        return self._request("GET", f"/v1/census-batches/{batch_id}", headers=headers)

    def add_participants(self, batch_id, payload, headers):
        return self._request("POST", f"/v1/census-batches/{batch_id}/participants", payload, headers)

    def list_participants(self, batch_id, headers, params=None):
        return self._request("GET", f"/v1/census-batches/{batch_id}/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/v1/participants/{participant_id}", headers=headers)

    def submit_screening(self, batch_id, headers):
        return self._request("POST", f"/v1/census-batches/{batch_id}/submit-screening", {}, headers)

    def lock_census_batch(self, batch_id, headers):
        return self._request("POST", f"/v1/census-batches/{batch_id}/lock", {}, headers)

    # --- Assumption sets ---
    def create_assumption_set(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/assumption-sets", payload, headers)

    def list_assumption_sets(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/assumption-sets", headers=headers, params=params)

    def get_assumption_set(self, aset_id, headers):
        return self._request("GET", f"/v1/assumption-sets/{aset_id}", headers=headers)

    def submit_assumption_set(self, aset_id, headers):
        return self._request("POST", f"/v1/assumption-sets/{aset_id}/submit", {}, headers)

    def approve_assumption_set(self, aset_id, headers):
        return self._request("POST", f"/v1/assumption-sets/{aset_id}/approve", {}, headers)

    def reject_assumption_set(self, aset_id, headers):
        return self._request("POST", f"/v1/assumption-sets/{aset_id}/reject", {}, headers)

    def lock_assumption_set(self, aset_id, headers):
        return self._request("POST", f"/v1/assumption-sets/{aset_id}/lock", {}, headers)

    def reopen_assumption_set(self, aset_id, headers):
        return self._request("POST", f"/v1/assumption-sets/{aset_id}/reopen", {}, headers)

    def retire_assumption_set(self, aset_id, headers):
        return self._request("POST", f"/v1/assumption-sets/{aset_id}/retire", {}, headers)

    # --- Asset statements / valuations ---
    def create_asset_statement(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/asset-statements", payload, headers)

    def list_asset_statements(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/asset-statements", headers=headers, params=params)

    def create_asset_valuation(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/asset-valuations", payload, headers)

    def list_asset_valuations(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/asset-valuations", headers=headers, params=params)

    def get_asset_valuation(self, ava_id, headers):
        return self._request("GET", f"/v1/asset-valuations/{ava_id}", headers=headers)

    # --- Valuation runs ---
    def create_valuation_run(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/valuation-runs", payload, headers)

    def list_valuation_runs(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/valuation-runs", headers=headers, params=params)

    def get_valuation_run(self, run_id, headers):
        return self._request("GET", f"/v1/valuation-runs/{run_id}", headers=headers)

    def compute_valuation_run(self, run_id, headers):
        return self._request("POST", f"/v1/valuation-runs/{run_id}/compute", {}, headers)

    def certify_valuation_run(self, run_id, payload, headers):
        return self._request("POST", f"/v1/valuation-runs/{run_id}/certify", payload, headers)

    def void_valuation_run(self, run_id, headers):
        return self._request("POST", f"/v1/valuation-runs/{run_id}/void", {}, headers)

    # --- Reverse-reachability list endpoints ---
    def list_runs_by_census_batch(self, batch_id, headers, params=None):
        return self._request("GET", f"/v1/census-batches/{batch_id}/valuation-runs", headers=headers, params=params)

    def list_runs_by_assumption_set(self, aset_id, headers, params=None):
        return self._request("GET", f"/v1/assumption-sets/{aset_id}/valuation-runs", headers=headers, params=params)

    def list_runs_by_asset_valuation(self, ava_id, headers, params=None):
        return self._request("GET", f"/v1/asset-valuations/{ava_id}/valuation-runs", headers=headers, params=params)

    def list_demands_by_run(self, run_id, headers, params=None):
        return self._request("GET", f"/v1/valuation-runs/{run_id}/contribution-demands", headers=headers, params=params)

    def list_filings_by_run(self, run_id, headers, params=None):
        return self._request("GET", f"/v1/valuation-runs/{run_id}/pbgc-filings", headers=headers, params=params)

    def list_reports_by_run(self, run_id, headers, params=None):
        return self._request("GET", f"/v1/valuation-runs/{run_id}/disclosure-reports", headers=headers, params=params)

    def list_accruals_by_run(self, run_id, headers, params=None):
        return self._request("GET", f"/v1/valuation-runs/{run_id}/accruals", headers=headers, params=params)

    def list_accruals_by_participant(self, participant_id, headers, params=None):
        return self._request("GET", f"/v1/participants/{participant_id}/accruals", headers=headers, params=params)

    # --- Credit balance ledger / elections ---
    def get_credit_balance_ledger(self, plan_id, headers):
        return self._request("GET", f"/v1/plans/{plan_id}/credit-balance-ledger", headers=headers)

    def create_credit_balance_election(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/credit-balance-elections", payload, headers)

    def list_credit_balance_elections(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/credit-balance-elections", headers=headers, params=params)

    def revoke_credit_balance_election(self, election_id, headers):
        return self._request("POST", f"/v1/credit-balance-elections/{election_id}/revoke", {}, headers)

    # --- Contribution demands / payments ---
    def get_contribution_demand(self, demand_id, headers):
        return self._request("GET", f"/v1/contribution-demands/{demand_id}", headers=headers)

    def list_contribution_demands(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/contribution-demands", headers=headers, params=params)

    def list_elections_by_demand(self, demand_id, headers, params=None):
        return self._request("GET", f"/v1/contribution-demands/{demand_id}/elections", headers=headers, params=params)

    def create_contribution_payment(self, demand_id, payload, headers):
        return self._request("POST", f"/v1/contribution-demands/{demand_id}/payments", payload, headers)

    def list_contribution_payments(self, demand_id, headers, params=None):
        return self._request("GET", f"/v1/contribution-demands/{demand_id}/payments", headers=headers, params=params)

    # --- PBGC filings ---
    def create_pbgc_filing(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/pbgc-filings", payload, headers)

    def list_pbgc_filings(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/pbgc-filings", headers=headers, params=params)

    def get_pbgc_filing(self, filing_id, headers):
        return self._request("GET", f"/v1/pbgc-filings/{filing_id}", headers=headers)

    def file_pbgc_filing(self, filing_id, headers):
        return self._request("POST", f"/v1/pbgc-filings/{filing_id}/file", {}, headers)

    def amend_pbgc_filing(self, filing_id, headers):
        return self._request("POST", f"/v1/pbgc-filings/{filing_id}/amend", {}, headers)

    def void_pbgc_filing(self, filing_id, headers):
        return self._request("POST", f"/v1/pbgc-filings/{filing_id}/void", {}, headers)

    # --- Disclosure reports ---
    def create_disclosure_report(self, plan_id, payload, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/disclosure-reports", payload, headers)

    def list_disclosure_reports(self, plan_id, headers, params=None):
        return self._request("GET", f"/v1/plans/{plan_id}/disclosure-reports", headers=headers, params=params)

    def get_disclosure_report(self, report_id, headers):
        return self._request("GET", f"/v1/disclosure-reports/{report_id}", headers=headers)

    def acknowledge_disclosure_report(self, report_id, headers):
        return self._request("POST", f"/v1/disclosure-reports/{report_id}/acknowledge", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
