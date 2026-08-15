"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/household-payroll/_clock/set_current_utc", payload, headers)

    # --- employers ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/household-payroll/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/household-payroll/employers/{employer_id}", headers=headers)

    def suspend_employer(self, employer_id, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/suspend", headers=headers)

    def reinstate_employer(self, employer_id, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/reinstate", headers=headers)

    # --- state rule packs ---
    def create_state_rule_pack(self, payload, headers):
        return self._request("POST", "/household-payroll/state-rule-packs", payload, headers)

    def list_state_rule_packs(self, headers, params=None):
        return self._request("GET", "/household-payroll/state-rule-packs", headers=headers, params=params)

    # --- registrations ---
    def create_registration(self, employer_id, payload, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/registrations", payload, headers)

    def submit_registration(self, registration_id, headers):
        return self._request("POST", f"/household-payroll/registrations/{registration_id}/submit", headers=headers)

    def activate_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/household-payroll/registrations/{registration_id}/activate", payload, headers)

    def list_registrations(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/registrations", headers=headers, params=params)

    # --- workers ---
    def create_worker(self, employer_id, payload, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/household-payroll/workers/{worker_id}", headers=headers)

    def list_workers(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/workers", headers=headers, params=params)

    def classify_worker(self, worker_id, payload, headers):
        return self._request("POST", f"/household-payroll/workers/{worker_id}/classify", payload, headers)

    def activate_worker(self, worker_id, payload, headers):
        return self._request("POST", f"/household-payroll/workers/{worker_id}/activate", payload, headers)

    def terminate_worker(self, worker_id, headers):
        return self._request("POST", f"/household-payroll/workers/{worker_id}/terminate", headers=headers)

    # --- agreements ---
    def create_agreement(self, worker_id, payload, headers):
        return self._request("POST", f"/household-payroll/workers/{worker_id}/agreements", payload, headers)

    def list_agreements(self, worker_id, headers, params=None):
        return self._request("GET", f"/household-payroll/workers/{worker_id}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/household-payroll/agreements/{agreement_id}", headers=headers)

    def list_superseded_agreements(self, agreement_id, headers, params=None):
        return self._request("GET", f"/household-payroll/agreements/{agreement_id}/superseded", headers=headers, params=params)

    # --- timesheets ---
    def create_timesheet(self, worker_id, payload, headers):
        return self._request("POST", f"/household-payroll/workers/{worker_id}/timesheets", payload, headers)

    def submit_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/household-payroll/timesheets/{timesheet_id}/submit", headers=headers)

    def approve_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/household-payroll/timesheets/{timesheet_id}/approve", headers=headers)

    def reject_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/household-payroll/timesheets/{timesheet_id}/reject", headers=headers)

    def get_timesheet(self, timesheet_id, headers):
        return self._request("GET", f"/household-payroll/timesheets/{timesheet_id}", headers=headers)

    def list_worker_timesheets(self, worker_id, headers, params=None):
        return self._request("GET", f"/household-payroll/workers/{worker_id}/timesheets", headers=headers, params=params)

    # --- pay runs ---
    def create_pay_run(self, employer_id, payload, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/pay-runs", payload, headers)

    def get_pay_run(self, pay_run_id, headers):
        return self._request("GET", f"/household-payroll/pay-runs/{pay_run_id}", headers=headers)

    def list_pay_runs(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/pay-runs", headers=headers, params=params)

    def calculate_pay_run(self, pay_run_id, headers):
        return self._request("POST", f"/household-payroll/pay-runs/{pay_run_id}/calculate", headers=headers)

    def finalize_pay_run(self, pay_run_id, headers):
        return self._request("POST", f"/household-payroll/pay-runs/{pay_run_id}/finalize", headers=headers)

    def list_pay_run_paychecks(self, pay_run_id, headers, params=None):
        return self._request("GET", f"/household-payroll/pay-runs/{pay_run_id}/paychecks", headers=headers, params=params)

    def list_pay_run_timesheets(self, pay_run_id, headers, params=None):
        return self._request("GET", f"/household-payroll/pay-runs/{pay_run_id}/timesheets", headers=headers, params=params)

    # --- paychecks ---
    def get_paycheck(self, paycheck_id, headers):
        return self._request("GET", f"/household-payroll/paychecks/{paycheck_id}", headers=headers)

    def void_paycheck(self, paycheck_id, headers):
        return self._request("POST", f"/household-payroll/paychecks/{paycheck_id}/void", headers=headers)

    def list_worker_paychecks(self, worker_id, headers, params=None):
        return self._request("GET", f"/household-payroll/workers/{worker_id}/paychecks", headers=headers, params=params)

    # --- leave ---
    def create_leave_request(self, worker_id, payload, headers):
        return self._request("POST", f"/household-payroll/workers/{worker_id}/leave-requests", payload, headers)

    def approve_leave_request(self, leave_id, headers):
        return self._request("POST", f"/household-payroll/leave-requests/{leave_id}/approve", headers=headers)

    def deny_leave_request(self, leave_id, headers):
        return self._request("POST", f"/household-payroll/leave-requests/{leave_id}/deny", headers=headers)

    def cancel_leave_request(self, leave_id, headers):
        return self._request("POST", f"/household-payroll/leave-requests/{leave_id}/cancel", headers=headers)

    def list_leave_requests(self, worker_id, headers, params=None):
        return self._request("GET", f"/household-payroll/workers/{worker_id}/leave-requests", headers=headers, params=params)

    # --- tax ledger ---
    def list_tax_accounts(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/tax-accounts", headers=headers, params=params)

    def create_deposit(self, employer_id, payload, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/deposits", payload, headers)

    def list_deposits(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/deposits", headers=headers, params=params)

    # --- quarterly filings ---
    def create_quarterly_filing(self, employer_id, payload, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/quarterly-filings", payload, headers)

    def prepare_quarterly_filing(self, filing_id, headers):
        return self._request("POST", f"/household-payroll/quarterly-filings/{filing_id}/prepare", headers=headers)

    def submit_quarterly_filing(self, filing_id, headers):
        return self._request("POST", f"/household-payroll/quarterly-filings/{filing_id}/submit", headers=headers)

    def accept_quarterly_filing(self, filing_id, headers):
        return self._request("POST", f"/household-payroll/quarterly-filings/{filing_id}/accept", headers=headers)

    def reject_quarterly_filing(self, filing_id, headers):
        return self._request("POST", f"/household-payroll/quarterly-filings/{filing_id}/reject", headers=headers)

    def list_quarterly_filings(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/quarterly-filings", headers=headers, params=params)

    # --- workers' compensation ---
    def create_workers_comp_policy(self, employer_id, payload, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/workers-comp-policies", payload, headers)

    def bind_workers_comp_policy(self, policy_id, headers):
        return self._request("POST", f"/household-payroll/workers-comp-policies/{policy_id}/bind", headers=headers)

    def lapse_workers_comp_policy(self, policy_id, headers):
        return self._request("POST", f"/household-payroll/workers-comp-policies/{policy_id}/lapse", headers=headers)

    def list_workers_comp_policies(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/workers-comp-policies", headers=headers, params=params)

    # --- year-end ---
    def create_year_end_package(self, employer_id, payload, headers):
        return self._request("POST", f"/household-payroll/employers/{employer_id}/year-end-packages", payload, headers)

    def finalize_year_end_package(self, package_id, headers):
        return self._request("POST", f"/household-payroll/year-end-packages/{package_id}/finalize", headers=headers)

    def list_year_end_packages(self, employer_id, headers, params=None):
        return self._request("GET", f"/household-payroll/employers/{employer_id}/year-end-packages", headers=headers, params=params)


api_client = ApiClient()
