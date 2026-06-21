"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Employer / configuration ----
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def list_employer_wage_rulesets(self, employer_id, headers, params=None):
        return self._request("GET", f"/employers/{employer_id}/wage-rulesets", headers=headers, params=params)

    def create_wage_ruleset(self, payload, headers):
        return self._request("POST", "/wage-rulesets", payload, headers)

    def create_worksite(self, payload, headers):
        return self._request("POST", "/worksites", payload, headers)

    def list_worksites(self, headers, params=None):
        return self._request("GET", "/worksites", headers=headers, params=params)

    def get_worksite(self, worksite_id, headers):
        return self._request("GET", f"/worksites/{worksite_id}", headers=headers)

    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    # ---- Shift + punch ----
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/cancel", {}, headers)

    def open_punch(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/punches", payload, headers)

    def list_shift_punches(self, shift_id, headers, params=None):
        return self._request("GET", f"/shifts/{shift_id}/punches", headers=headers, params=params)

    def list_punches(self, headers, params=None):
        return self._request("GET", "/punches", headers=headers, params=params)

    def get_punch(self, punch_id, headers):
        return self._request("GET", f"/punches/{punch_id}", headers=headers)

    def close_punch(self, punch_id, payload, headers):
        return self._request("POST", f"/punches/{punch_id}/close", payload, headers)

    def edit_punch(self, punch_id, payload, headers):
        return self._request("POST", f"/punches/{punch_id}/edits", payload, headers)

    def list_punch_edits(self, punch_id, headers, params=None):
        return self._request("GET", f"/punches/{punch_id}/edits", headers=headers, params=params)

    def void_punch(self, punch_id, headers):
        return self._request("POST", f"/punches/{punch_id}/void", {}, headers)

    # ---- Break records ----
    def create_break_record(self, payload, headers):
        return self._request("POST", "/break-records", payload, headers)

    def list_break_records(self, headers, params=None):
        return self._request("GET", "/break-records", headers=headers, params=params)

    def get_break_record(self, break_record_id, headers):
        return self._request("GET", f"/break-records/{break_record_id}", headers=headers)

    # ---- Tips ----
    def create_tip_declaration(self, payload, headers):
        return self._request("POST", "/tip-declarations", payload, headers)

    def list_tip_declarations(self, headers, params=None):
        return self._request("GET", "/tip-declarations", headers=headers, params=params)

    def get_tip_declaration(self, tip_declaration_id, headers):
        return self._request("GET", f"/tip-declarations/{tip_declaration_id}", headers=headers)

    def create_tip_pool(self, payload, headers):
        return self._request("POST", "/tip-pools", payload, headers)

    def list_tip_pools(self, headers, params=None):
        return self._request("GET", "/tip-pools", headers=headers, params=params)

    def get_tip_pool(self, tip_pool_id, headers):
        return self._request("GET", f"/tip-pools/{tip_pool_id}", headers=headers)

    def distribute_tip_pool(self, tip_pool_id, headers):
        return self._request("POST", f"/tip-pools/{tip_pool_id}/distribute", {}, headers)

    def cancel_tip_pool(self, tip_pool_id, headers):
        return self._request("POST", f"/tip-pools/{tip_pool_id}/cancel", {}, headers)

    # ---- Timesheet week ----
    def create_timesheet_week(self, payload, headers):
        return self._request("POST", "/timesheet-weeks", payload, headers)

    def list_timesheet_weeks(self, headers, params=None):
        return self._request("GET", "/timesheet-weeks", headers=headers, params=params)

    def get_timesheet_week(self, week_id, headers):
        return self._request("GET", f"/timesheet-weeks/{week_id}", headers=headers)

    def submit_timesheet_week(self, week_id, headers):
        return self._request("POST", f"/timesheet-weeks/{week_id}/submit", {}, headers)

    def approve_timesheet_week(self, week_id, payload, headers):
        return self._request("POST", f"/timesheet-weeks/{week_id}/approve", payload, headers)

    def reject_timesheet_week(self, week_id, headers):
        return self._request("POST", f"/timesheet-weeks/{week_id}/reject", {}, headers)

    # ---- Payroll run ----
    def create_payroll_run(self, payload, headers):
        return self._request("POST", "/payroll-runs", payload, headers)

    def list_payroll_runs(self, headers, params=None):
        return self._request("GET", "/payroll-runs", headers=headers, params=params)

    def get_payroll_run(self, run_id, headers):
        return self._request("GET", f"/payroll-runs/{run_id}", headers=headers)

    def include_week_in_run(self, run_id, payload, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/include", payload, headers)

    def finalize_payroll_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/finalize", {}, headers)

    def cancel_payroll_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/cancel", {}, headers)


api_client = ApiClient()
