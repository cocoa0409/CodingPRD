"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = ""


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    # --- Issuers ---
    def create_issuer(self, payload, headers):
        return self._request("POST", f"{BASE}/issuers", payload, headers)

    def list_issuers(self, headers, params=None):
        return self._request("GET", f"{BASE}/issuers", headers=headers, params=params)

    def get_issuer(self, issuer_id, headers):
        return self._request("GET", f"{BASE}/issuers/{issuer_id}", headers=headers)

    def update_issuer(self, issuer_id, payload, headers):
        return self._request("PUT", f"{BASE}/issuers/{issuer_id}", payload, headers)

    # --- Blackout windows ---
    def create_blackout_window(self, payload, headers):
        return self._request("POST", f"{BASE}/blackout-windows", payload, headers)

    def list_blackout_windows(self, headers, params=None):
        return self._request("GET", f"{BASE}/blackout-windows", headers=headers, params=params)

    def get_blackout_window(self, blackout_window_id, headers):
        return self._request("GET", f"{BASE}/blackout-windows/{blackout_window_id}", headers=headers)

    # --- Reporting persons ---
    def create_reporting_person(self, payload, headers):
        return self._request("POST", f"{BASE}/reporting-persons", payload, headers)

    def list_reporting_persons(self, headers, params=None):
        return self._request("GET", f"{BASE}/reporting-persons", headers=headers, params=params)

    def get_reporting_person(self, person_id, headers):
        return self._request("GET", f"{BASE}/reporting-persons/{person_id}", headers=headers)

    def person_transition(self, person_id, payload, headers):
        return self._request("POST", f"{BASE}/reporting-persons/{person_id}/transitions", payload, headers)

    def get_short_swing_analysis(self, person_id, headers):
        return self._request("GET", f"{BASE}/reporting-persons/{person_id}/short-swing-analysis", headers=headers)

    # --- Transactions ---
    def create_transaction(self, payload, headers):
        return self._request("POST", f"{BASE}/transactions", payload, headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", f"{BASE}/transactions", headers=headers, params=params)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"{BASE}/transactions/{transaction_id}", headers=headers)

    def confirm_transaction(self, transaction_id, headers):
        return self._request("POST", f"{BASE}/transactions/{transaction_id}/confirm", {}, headers)

    def void_transaction(self, transaction_id, payload, headers):
        return self._request("POST", f"{BASE}/transactions/{transaction_id}/void", payload, headers)

    # --- Filings ---
    def create_filing(self, payload, headers):
        return self._request("POST", f"{BASE}/filings", payload, headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", f"{BASE}/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"{BASE}/filings/{filing_id}", headers=headers)

    def ready_filing(self, filing_id, headers):
        return self._request("POST", f"{BASE}/filings/{filing_id}/ready", {}, headers)

    def reopen_filing(self, filing_id, headers):
        return self._request("POST", f"{BASE}/filings/{filing_id}/reopen", {}, headers)

    def discard_filing(self, filing_id, headers):
        return self._request("POST", f"{BASE}/filings/{filing_id}/discard", {}, headers)

    def submit_filing(self, filing_id, payload, headers):
        return self._request("POST", f"{BASE}/filings/{filing_id}/submit", payload, headers)

    def record_edgar_result(self, filing_id, payload, headers):
        return self._request("POST", f"{BASE}/filings/{filing_id}/record-edgar-result", payload, headers)

    def create_amendment(self, filing_id, payload, headers):
        return self._request("POST", f"{BASE}/filings/{filing_id}/amendments", payload, headers)

    # --- Trading plans (10b5-1) ---
    def create_trading_plan(self, payload, headers):
        return self._request("POST", f"{BASE}/trading-plans", payload, headers)

    def list_trading_plans(self, headers, params=None):
        return self._request("GET", f"{BASE}/trading-plans", headers=headers, params=params)

    def get_trading_plan(self, plan_id, headers):
        return self._request("GET", f"{BASE}/trading-plans/{plan_id}", headers=headers)

    def plan_transition(self, plan_id, payload, headers):
        return self._request("POST", f"{BASE}/trading-plans/{plan_id}/transitions", payload, headers)

    # --- Beneficial ownership (13D/G) ---
    def create_beneficial_holder(self, payload, headers):
        return self._request("POST", f"{BASE}/beneficial-holders", payload, headers)

    def list_beneficial_holders(self, headers, params=None):
        return self._request("GET", f"{BASE}/beneficial-holders", headers=headers, params=params)

    def get_beneficial_holder(self, holder_id, headers):
        return self._request("GET", f"{BASE}/beneficial-holders/{holder_id}", headers=headers)

    def post_position_change(self, holder_id, payload, headers):
        return self._request("POST", f"{BASE}/beneficial-holders/{holder_id}/positions", payload, headers)

    def list_position_changes(self, headers, params=None):
        return self._request("GET", f"{BASE}/position-changes", headers=headers, params=params)

    def get_position_change(self, position_change_id, headers):
        return self._request("GET", f"{BASE}/position-changes/{position_change_id}", headers=headers)

    def file_schedule(self, holder_id, payload, headers):
        return self._request("POST", f"{BASE}/beneficial-holders/{holder_id}/file-schedule", payload, headers)

    # --- Annual sweep ---
    def create_annual_sweep(self, payload, headers):
        return self._request("POST", f"{BASE}/annual-sweeps", payload, headers)

    def list_annual_sweeps(self, headers, params=None):
        return self._request("GET", f"{BASE}/annual-sweeps", headers=headers, params=params)

    def get_annual_sweep(self, sweep_id, headers):
        return self._request("GET", f"{BASE}/annual-sweeps/{sweep_id}", headers=headers)

    def run_annual_sweep(self, sweep_id, headers):
        return self._request("POST", f"{BASE}/annual-sweeps/{sweep_id}/run", {}, headers)

    # --- Filing agent authorizations ---
    def create_filing_agent_authorization(self, payload, headers):
        return self._request("POST", f"{BASE}/filing-agent-authorizations", payload, headers)

    def list_filing_agent_authorizations(self, headers, params=None):
        return self._request("GET", f"{BASE}/filing-agent-authorizations", headers=headers, params=params)

    def get_filing_agent_authorization(self, authorization_id, headers):
        return self._request("GET", f"{BASE}/filing-agent-authorizations/{authorization_id}", headers=headers)

    def revoke_filing_agent_authorization(self, authorization_id, headers):
        return self._request("POST", f"{BASE}/filing-agent-authorizations/{authorization_id}/revoke", {}, headers)


api_client = ApiClient()
