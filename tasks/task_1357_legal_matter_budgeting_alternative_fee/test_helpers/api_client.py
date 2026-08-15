"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Firm ---
    def create_firm(self, payload, headers):
        return self._request("POST", "/firms", payload, headers)

    def get_firm(self, firm_id, headers):
        return self._request("GET", f"/firms/{firm_id}", headers=headers)

    def advance_period(self, firm_id, headers):
        return self._request("POST", f"/firms/{firm_id}/advance_period",
                             headers=headers)

    def close_books(self, firm_id, headers):
        return self._request("POST", f"/firms/{firm_id}/close_books",
                             headers=headers)

    # --- Timekeeper ---
    def create_timekeeper(self, firm_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/timekeepers",
                             payload, headers)

    def get_timekeeper(self, timekeeper_id, headers):
        return self._request("GET", f"/firms/timekeepers/{timekeeper_id}",
                             headers=headers)

    def list_timekeepers(self, headers, params=None):
        return self._request("GET", "/firms/timekeepers",
                             headers=headers, params=params)

    # --- Client ---
    def create_client(self, firm_id, payload, headers):
        return self._request("POST", f"/firms/{firm_id}/clients",
                             payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/firms/clients/{client_id}",
                             headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/firms/clients",
                             headers=headers, params=params)

    def suspend_client(self, firm_id, client_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/clients/{client_id}/suspend",
            headers=headers)

    def activate_client(self, firm_id, client_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/clients/{client_id}/activate",
            headers=headers)

    def close_client(self, firm_id, client_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/clients/{client_id}/close",
            headers=headers)

    # --- Matter ---
    def create_matter(self, firm_id, client_id, payload, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/clients/{client_id}/matters",
            payload, headers)

    def get_matter(self, matter_id, headers):
        return self._request("GET", f"/firms/matters/{matter_id}",
                             headers=headers)

    def list_matters(self, headers, params=None):
        return self._request("GET", "/firms/matters",
                             headers=headers, params=params)

    def list_client_matters(self, client_id, headers, params=None):
        return self._request("GET", f"/firms/clients/{client_id}/matters",
                             headers=headers, params=params)

    def suspend_matter(self, firm_id, matter_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/matters/{matter_id}/suspend",
            headers=headers)

    def resume_matter(self, firm_id, matter_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/matters/{matter_id}/resume",
            headers=headers)

    def close_matter(self, firm_id, matter_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/matters/{matter_id}/close",
            headers=headers)

    def reopen_matter(self, firm_id, matter_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/matters/{matter_id}/reopen",
            headers=headers)

    def get_matter_quote(self, firm_id, matter_id, headers, params=None):
        return self._request(
            "GET", f"/firms/{firm_id}/matters/{matter_id}/quote",
            headers=headers, params=params)

    def get_matter_variance(self, firm_id, matter_id, headers):
        return self._request(
            "GET", f"/firms/{firm_id}/matters/{matter_id}/variance",
            headers=headers)

    # --- FeeArrangement ---
    def create_fee_arrangement(self, firm_id, matter_id, payload, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/matters/{matter_id}/fee_arrangements",
            payload, headers)

    def get_fee_arrangement(self, arrangement_id, headers):
        return self._request(
            "GET", f"/firms/fee_arrangements/{arrangement_id}",
            headers=headers)

    def list_fee_arrangements(self, headers, params=None):
        return self._request("GET", "/firms/fee_arrangements",
                             headers=headers, params=params)

    def list_matter_fee_arrangements(self, matter_id, headers, params=None):
        return self._request(
            "GET", f"/firms/matters/{matter_id}/fee_arrangements",
            headers=headers, params=params)

    def submit_fee_arrangement(self, firm_id, arrangement_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/fee_arrangements/{arrangement_id}/submit",
            headers=headers)

    def activate_fee_arrangement(self, firm_id, arrangement_id, payload,
                                 headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/fee_arrangements/{arrangement_id}/activate",
            payload, headers)

    def reject_fee_arrangement(self, firm_id, arrangement_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/fee_arrangements/{arrangement_id}/reject",
            headers=headers)

    # --- PhaseBudget ---
    def create_phase_budget(self, firm_id, matter_id, payload, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/matters/{matter_id}/phase_budgets",
            payload, headers)

    def get_phase_budget(self, phase_budget_id, headers):
        return self._request("GET", f"/firms/phase_budgets/{phase_budget_id}",
                             headers=headers)

    def list_phase_budgets(self, headers, params=None):
        return self._request("GET", "/firms/phase_budgets",
                             headers=headers, params=params)

    def list_matter_phase_budgets(self, matter_id, headers, params=None):
        return self._request("GET",
                             f"/firms/matters/{matter_id}/phase_budgets",
                             headers=headers, params=params)

    def activate_phase_budget(self, firm_id, phase_budget_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/phase_budgets/{phase_budget_id}/activate",
            headers=headers)

    def void_phase_budget(self, firm_id, phase_budget_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/phase_budgets/{phase_budget_id}/void",
            headers=headers)

    def update_phase_budget_etc(self, phase_budget_id, payload, headers):
        return self._request("PATCH",
                             f"/firms/phase_budgets/{phase_budget_id}",
                             payload, headers)

    # --- TimeEntry ---
    def create_time_entry(self, firm_id, matter_id, payload, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/matters/{matter_id}/time_entries",
            payload, headers)

    def get_time_entry(self, entry_id, headers):
        return self._request("GET", f"/firms/time_entries/{entry_id}",
                             headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/firms/time_entries",
                             headers=headers, params=params)

    def list_matter_time_entries(self, matter_id, headers, params=None):
        return self._request("GET",
                             f"/firms/matters/{matter_id}/time_entries",
                             headers=headers, params=params)

    def submit_time_entry(self, firm_id, entry_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/time_entries/{entry_id}/submit",
            headers=headers)

    def approve_time_entry(self, firm_id, entry_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/time_entries/{entry_id}/approve",
            headers=headers)

    def mark_time_entry_billed(self, firm_id, entry_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/time_entries/{entry_id}/mark_billed",
            headers=headers)

    def reject_time_entry(self, firm_id, entry_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/time_entries/{entry_id}/reject",
            headers=headers)

    # --- WriteDownRequest ---
    def create_write_down_request(self, firm_id, matter_id, payload, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/matters/{matter_id}/write_down_requests",
            payload, headers)

    def get_write_down_request(self, request_id, headers):
        return self._request("GET",
                             f"/firms/write_down_requests/{request_id}",
                             headers=headers)

    def list_write_down_requests(self, headers, params=None):
        return self._request("GET", "/firms/write_down_requests",
                             headers=headers, params=params)

    def list_matter_write_down_requests(self, matter_id, headers,
                                        params=None):
        return self._request(
            "GET", f"/firms/matters/{matter_id}/write_down_requests",
            headers=headers, params=params)

    def submit_write_down_request(self, firm_id, request_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/write_down_requests/{request_id}/submit",
            headers=headers)

    def decide_write_down_request(self, firm_id, request_id, payload,
                                  headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/write_down_requests/{request_id}/decide",
            payload, headers)

    def apply_write_down_request(self, firm_id, request_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/write_down_requests/{request_id}/apply",
            headers=headers)

    def cancel_write_down_request(self, firm_id, request_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/write_down_requests/{request_id}/cancel",
            headers=headers)

    # --- BudgetAmendment ---
    def create_budget_amendment(self, firm_id, matter_id, payload, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/matters/{matter_id}/budget_amendments",
            payload, headers)

    def get_budget_amendment(self, amendment_id, headers):
        return self._request("GET",
                             f"/firms/budget_amendments/{amendment_id}",
                             headers=headers)

    def list_budget_amendments(self, headers, params=None):
        return self._request("GET", "/firms/budget_amendments",
                             headers=headers, params=params)

    def list_matter_budget_amendments(self, matter_id, headers, params=None):
        return self._request(
            "GET", f"/firms/matters/{matter_id}/budget_amendments",
            headers=headers, params=params)

    def list_phase_budget_amendments(self, phase_budget_id, headers,
                                     params=None):
        return self._request(
            "GET",
            f"/firms/phase_budgets/{phase_budget_id}/budget_amendments",
            headers=headers, params=params)

    def submit_budget_amendment(self, firm_id, amendment_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/budget_amendments/{amendment_id}/submit",
            headers=headers)

    def decide_budget_amendment(self, firm_id, amendment_id, payload,
                                headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/budget_amendments/{amendment_id}/decide",
            payload, headers)

    # --- AccrualReport ---
    def get_accrual_report(self, report_id, headers):
        return self._request("GET", f"/firms/accrual_reports/{report_id}",
                             headers=headers)

    def list_accrual_reports(self, headers, params=None):
        return self._request("GET", "/firms/accrual_reports",
                             headers=headers, params=params)

    def list_matter_accrual_reports(self, matter_id, headers, params=None):
        return self._request("GET",
                             f"/firms/matters/{matter_id}/accrual_reports",
                             headers=headers, params=params)

    def submit_accrual_report(self, firm_id, report_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/accrual_reports/{report_id}/submit",
            headers=headers)

    def acknowledge_accrual_report(self, firm_id, report_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/accrual_reports/{report_id}/acknowledge",
            headers=headers)

    def dispute_accrual_report(self, firm_id, report_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/accrual_reports/{report_id}/dispute",
            headers=headers)

    def resubmit_accrual_report(self, firm_id, report_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/accrual_reports/{report_id}/resubmit",
            headers=headers)

    # --- CollarTrueUp ---
    def run_year_end_collar_true_up(self, firm_id, matter_id, headers):
        return self._request(
            "POST",
            f"/firms/{firm_id}/matters/{matter_id}/run_year_end_collar_true_up",
            headers=headers)

    def get_collar_true_up(self, true_up_id, headers):
        return self._request("GET", f"/firms/collar_true_ups/{true_up_id}",
                             headers=headers)

    def list_collar_true_ups(self, headers, params=None):
        return self._request("GET", "/firms/collar_true_ups",
                             headers=headers, params=params)

    def list_matter_collar_true_ups(self, matter_id, headers, params=None):
        return self._request("GET",
                             f"/firms/matters/{matter_id}/collar_true_ups",
                             headers=headers, params=params)

    def settle_collar_true_up(self, firm_id, true_up_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/collar_true_ups/{true_up_id}/settle",
            headers=headers)

    def waive_collar_true_up(self, firm_id, true_up_id, headers):
        return self._request(
            "POST", f"/firms/{firm_id}/collar_true_ups/{true_up_id}/waive",
            headers=headers)

    # --- Logical clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             payload, headers)


api_client = ApiClient()
