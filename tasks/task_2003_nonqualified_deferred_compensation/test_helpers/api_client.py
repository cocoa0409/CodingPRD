"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/api/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/api/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}", headers=headers)

    def amend_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/api/plans/{plan_id}", payload, headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/api/plans/{plan_id}/activate", headers=headers)

    def suspend_plan(self, plan_id, headers):
        return self._request("POST", f"/api/plans/{plan_id}/suspend", headers=headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/api/plans/{plan_id}/resume", headers=headers)

    def terminate_plan(self, plan_id, headers):
        return self._request("POST", f"/api/plans/{plan_id}/terminate", headers=headers)

    # --- Election windows ---
    def create_election_window(self, payload, headers):
        return self._request("POST", "/api/election-windows", payload, headers)

    def list_election_windows(self, headers, params=None):
        return self._request("GET", "/api/election-windows", headers=headers, params=params)

    def get_election_window(self, window_id, headers):
        return self._request("GET", f"/api/election-windows/{window_id}", headers=headers)

    # --- Participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/api/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/api/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/api/participants/{participant_id}", headers=headers)

    def update_participant(self, participant_id, payload, headers):
        return self._request("PATCH", f"/api/participants/{participant_id}", payload, headers)

    def rehire_participant(self, participant_id, headers):
        return self._request("POST", f"/api/participants/{participant_id}/rehire", headers=headers)

    # --- Notional funds ---
    def create_notional_fund(self, payload, headers):
        return self._request("POST", "/api/notional-funds", payload, headers)

    def list_notional_funds(self, headers, params=None):
        return self._request("GET", "/api/notional-funds", headers=headers, params=params)

    def get_notional_fund(self, fund_id, headers):
        return self._request("GET", f"/api/notional-funds/{fund_id}", headers=headers)

    # --- Deferral elections ---
    def create_deferral_election(self, payload, headers):
        return self._request("POST", "/api/deferral-elections", payload, headers)

    def list_deferral_elections(self, headers, params=None):
        return self._request("GET", "/api/deferral-elections", headers=headers, params=params)

    def get_deferral_election(self, election_id, headers):
        return self._request("GET", f"/api/deferral-elections/{election_id}", headers=headers)

    def submit_election(self, election_id, headers):
        return self._request("POST", f"/api/deferral-elections/{election_id}/submit", headers=headers)

    def void_election(self, election_id, headers):
        return self._request("POST", f"/api/deferral-elections/{election_id}/void", headers=headers)

    def post_deferral(self, election_id, payload, headers):
        return self._request("POST", f"/api/deferral-elections/{election_id}/post-deferral", payload, headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/api/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/api/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}", headers=headers)

    def get_account_statement(self, account_id, headers):
        return self._request("GET", f"/api/accounts/{account_id}/statement", headers=headers)

    def settle_entries(self, account_id, headers):
        return self._request("POST", f"/api/accounts/{account_id}/settle-entries", headers=headers)

    # --- Ledger ---
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/api/ledger-entries/{entry_id}", headers=headers)

    # --- Crediting runs ---
    def create_crediting_run(self, payload, headers):
        return self._request("POST", "/api/crediting-runs", payload, headers)

    def list_crediting_runs(self, headers, params=None):
        return self._request("GET", "/api/crediting-runs", headers=headers, params=params)

    def get_crediting_run(self, run_id, headers):
        return self._request("GET", f"/api/crediting-runs/{run_id}", headers=headers)

    def reverse_crediting_run(self, run_id, headers):
        return self._request("POST", f"/api/crediting-runs/{run_id}/reverse", headers=headers)

    # --- Rabbi trusts ---
    def create_rabbi_trust(self, payload, headers):
        return self._request("POST", "/api/rabbi-trusts", payload, headers)

    def list_rabbi_trusts(self, headers, params=None):
        return self._request("GET", "/api/rabbi-trusts", headers=headers, params=params)

    def get_rabbi_trust(self, trust_id, headers):
        return self._request("GET", f"/api/rabbi-trusts/{trust_id}", headers=headers)

    def post_funding_event(self, trust_id, payload, headers):
        return self._request("POST", f"/api/rabbi-trusts/{trust_id}/funding-events", payload, headers)

    # --- Separation cases ---
    def create_separation_case(self, payload, headers):
        return self._request("POST", "/api/separation-cases", payload, headers)

    def list_separation_cases(self, headers, params=None):
        return self._request("GET", "/api/separation-cases", headers=headers, params=params)

    def get_separation_case(self, case_id, headers):
        return self._request("GET", f"/api/separation-cases/{case_id}", headers=headers)

    def append_service_record(self, case_id, payload, headers):
        return self._request("POST", f"/api/separation-cases/{case_id}/service-records", payload, headers)

    def determine_case(self, case_id, payload, headers):
        return self._request("POST", f"/api/separation-cases/{case_id}/determine", payload, headers)

    def reopen_case(self, case_id, headers):
        return self._request("POST", f"/api/separation-cases/{case_id}/reopen", headers=headers)

    # --- Specified employee lists ---
    def create_specified_employee_list(self, payload, headers):
        return self._request("POST", "/api/specified-employee-lists", payload, headers)

    def list_specified_employee_lists(self, headers, params=None):
        return self._request("GET", "/api/specified-employee-lists", headers=headers, params=params)

    def get_specified_employee_list(self, list_id, headers):
        return self._request("GET", f"/api/specified-employee-lists/{list_id}", headers=headers)

    def add_list_member(self, list_id, payload, headers):
        return self._request("POST", f"/api/specified-employee-lists/{list_id}/members", payload, headers)

    def finalize_list(self, list_id, headers):
        return self._request("POST", f"/api/specified-employee-lists/{list_id}/finalize", headers=headers)

    # --- Distribution requests ---
    def create_distribution_request(self, payload, headers):
        return self._request("POST", "/api/distribution-requests", payload, headers)

    def list_distribution_requests(self, headers, params=None):
        return self._request("GET", "/api/distribution-requests", headers=headers, params=params)

    def get_distribution_request(self, request_id, headers):
        return self._request("GET", f"/api/distribution-requests/{request_id}", headers=headers)

    def verify_distribution_event(self, request_id, headers):
        return self._request("POST", f"/api/distribution-requests/{request_id}/verify-event", headers=headers)

    def schedule_distribution(self, request_id, headers):
        return self._request("POST", f"/api/distribution-requests/{request_id}/schedule", headers=headers)

    def pay_distribution(self, request_id, headers):
        return self._request("POST", f"/api/distribution-requests/{request_id}/pay", headers=headers)

    def deny_distribution(self, request_id, payload, headers):
        return self._request("POST", f"/api/distribution-requests/{request_id}/deny", payload, headers)

    # --- Change in control ---
    def create_cic_event(self, payload, headers):
        return self._request("POST", "/api/change-in-control-events", payload, headers)

    def list_cic_events(self, headers, params=None):
        return self._request("GET", "/api/change-in-control-events", headers=headers, params=params)

    def get_cic_event(self, cic_id, headers):
        return self._request("GET", f"/api/change-in-control-events/{cic_id}", headers=headers)

    def adjudicate_cic(self, cic_id, payload, headers):
        return self._request("POST", f"/api/change-in-control-events/{cic_id}/adjudicate", payload, headers)

    # --- Operational failures ---
    def create_operational_failure(self, payload, headers):
        return self._request("POST", "/api/operational-failures", payload, headers)

    def list_operational_failures(self, headers, params=None):
        return self._request("GET", "/api/operational-failures", headers=headers, params=params)

    def get_operational_failure(self, failure_id, headers):
        return self._request("GET", f"/api/operational-failures/{failure_id}", headers=headers)

    def quantify_failure(self, failure_id, payload, headers):
        return self._request("POST", f"/api/operational-failures/{failure_id}/quantify", payload, headers)

    def assess_inclusion(self, failure_id, headers):
        return self._request("POST", f"/api/operational-failures/{failure_id}/assess-inclusion", headers=headers)

    def correct_failure(self, failure_id, headers):
        return self._request("POST", f"/api/operational-failures/{failure_id}/correct", headers=headers)

    # --- Document findings ---
    def create_document_finding(self, payload, headers):
        return self._request("POST", "/api/document-findings", payload, headers)

    def list_document_findings(self, headers, params=None):
        return self._request("GET", "/api/document-findings", headers=headers, params=params)

    def get_document_finding(self, finding_id, headers):
        return self._request("GET", f"/api/document-findings/{finding_id}", headers=headers)

    def file_correction(self, finding_id, payload, headers):
        return self._request("POST", f"/api/document-findings/{finding_id}/file-correction", payload, headers)

    def adjudicate_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/api/document-findings/{finding_id}/adjudicate", payload, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
