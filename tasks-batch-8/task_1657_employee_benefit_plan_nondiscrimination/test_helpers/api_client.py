"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ndt/_clock/set_current_utc", payload, headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/ndt/employers", payload, headers)

    def archive_employer(self, employer_id, headers):
        return self._request("POST", f"/ndt/employers/{employer_id}/archive", {}, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/ndt/employers/{employer_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/ndt/employers", headers=headers, params=params)

    def list_plans_of_employer(self, employer_id, headers, params=None):
        return self._request("GET", f"/ndt/employers/{employer_id}/plans", headers=headers, params=params)

    def create_plan(self, employer_id, payload, headers):
        return self._request("POST", f"/ndt/employers/{employer_id}/plans", payload, headers)

    # --- Plan ---
    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/ndt/plans/{plan_id}", headers=headers)

    def list_plan_versions(self, plan_id, headers, params=None):
        return self._request("GET", f"/ndt/plans/{plan_id}/plan-versions", headers=headers, params=params)

    def create_plan_version(self, plan_id, payload, headers):
        return self._request("POST", f"/ndt/plans/{plan_id}/plan-versions", payload, headers)

    def list_plan_years_of_plan(self, plan_id, headers, params=None):
        return self._request("GET", f"/ndt/plans/{plan_id}/plan-years", headers=headers, params=params)

    def create_plan_year(self, plan_id, payload, headers):
        return self._request("POST", f"/ndt/plans/{plan_id}/plan-years", payload, headers)

    # --- PlanVersion ---
    def get_plan_version(self, version_id, headers):
        return self._request("GET", f"/ndt/plan-versions/{version_id}", headers=headers)

    def adopt_plan_version(self, version_id, headers):
        return self._request("POST", f"/ndt/plan-versions/{version_id}/adopt", {}, headers)

    # --- PlanYear ---
    def list_plan_years(self, headers, params=None):
        return self._request("GET", "/ndt/plan-years", headers=headers, params=params)

    def get_plan_year(self, plan_year_id, headers):
        return self._request("GET", f"/ndt/plan-years/{plan_year_id}", headers=headers)

    def open_census(self, plan_year_id, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/open-census", {}, headers)

    def lock_census(self, plan_year_id, payload, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/lock-census", payload, headers)

    def unlock_census(self, plan_year_id, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/unlock-census", {}, headers)

    def terminate_plan_year(self, plan_year_id, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/terminate", {}, headers)

    def file_plan_year(self, plan_year_id, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/file", {}, headers)

    def list_census_employees(self, plan_year_id, headers, params=None):
        return self._request("GET", f"/ndt/plan-years/{plan_year_id}/census-employees", headers=headers, params=params)

    def create_census_employee(self, plan_year_id, payload, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/census-employees", payload, headers)

    def list_test_runs(self, plan_year_id, headers, params=None):
        return self._request("GET", f"/ndt/plan-years/{plan_year_id}/test-runs", headers=headers, params=params)

    def create_test_run(self, plan_year_id, payload, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/test-runs", payload, headers)

    def list_corrections_of_plan_year(self, plan_year_id, headers, params=None):
        return self._request("GET", f"/ndt/plan-years/{plan_year_id}/corrections", headers=headers, params=params)

    def create_correction(self, plan_year_id, payload, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/corrections", payload, headers)

    def list_safe_harbor_elections(self, plan_year_id, headers, params=None):
        return self._request("GET", f"/ndt/plan-years/{plan_year_id}/safe-harbor-elections", headers=headers, params=params)

    def create_safe_harbor_election(self, plan_year_id, payload, headers):
        return self._request("POST", f"/ndt/plan-years/{plan_year_id}/safe-harbor-elections", payload, headers)

    # --- CensusEmployee ---
    def get_census_employee(self, employee_id, headers):
        return self._request("GET", f"/ndt/census-employees/{employee_id}", headers=headers)

    def patch_census_employee(self, employee_id, payload, headers):
        return self._request("PATCH", f"/ndt/census-employees/{employee_id}", payload, headers)

    def list_compensation_records(self, employee_id, headers, params=None):
        return self._request("GET", f"/ndt/census-employees/{employee_id}/compensation-records", headers=headers, params=params)

    def create_compensation_record(self, employee_id, payload, headers):
        return self._request("POST", f"/ndt/census-employees/{employee_id}/compensation-records", payload, headers)

    def list_contributions(self, employee_id, headers, params=None):
        return self._request("GET", f"/ndt/census-employees/{employee_id}/contributions", headers=headers, params=params)

    def create_contribution(self, employee_id, payload, headers):
        return self._request("POST", f"/ndt/census-employees/{employee_id}/contributions", payload, headers)

    # --- RegulatoryLimit ---
    def create_regulatory_limit(self, payload, headers):
        return self._request("POST", "/ndt/regulatory-limits", payload, headers)

    def list_regulatory_limits(self, headers, params=None):
        return self._request("GET", "/ndt/regulatory-limits", headers=headers, params=params)

    # --- TestRun / TestResultLine ---
    def get_test_run(self, test_run_id, headers):
        return self._request("GET", f"/ndt/test-runs/{test_run_id}", headers=headers)

    def list_result_lines(self, test_run_id, headers, params=None):
        return self._request("GET", f"/ndt/test-runs/{test_run_id}/result-lines", headers=headers, params=params)

    def finalize_test_run(self, test_run_id, headers):
        return self._request("POST", f"/ndt/test-runs/{test_run_id}/finalize", {}, headers)

    def void_test_run(self, test_run_id, headers):
        return self._request("POST", f"/ndt/test-runs/{test_run_id}/void", {}, headers)

    def execute_test_run_synchronously(self, test_run_id, headers):
        return self._request("POST", f"/ndt/test-runs/{test_run_id}/execute-synchronously", {}, headers)

    # --- Correction ---
    def list_corrections(self, headers, params=None):
        return self._request("GET", "/ndt/corrections", headers=headers, params=params)

    def get_correction(self, correction_id, headers):
        return self._request("GET", f"/ndt/corrections/{correction_id}", headers=headers)

    def approve_correction(self, correction_id, payload, headers):
        return self._request("POST", f"/ndt/corrections/{correction_id}/approve", payload, headers)

    def execute_correction(self, correction_id, headers):
        return self._request("POST", f"/ndt/corrections/{correction_id}/execute", {}, headers)

    def void_correction(self, correction_id, headers):
        return self._request("POST", f"/ndt/corrections/{correction_id}/void", {}, headers)

    # --- SafeHarborElection / Notice ---
    def get_safe_harbor_election(self, election_id, headers):
        return self._request("GET", f"/ndt/safe-harbor-elections/{election_id}", headers=headers)

    def suspend_safe_harbor_election(self, election_id, payload, headers):
        return self._request("POST", f"/ndt/safe-harbor-elections/{election_id}/suspend", payload, headers)

    def revoke_safe_harbor_election(self, election_id, headers):
        return self._request("POST", f"/ndt/safe-harbor-elections/{election_id}/revoke", {}, headers)

    def create_safe_harbor_notice(self, election_id, payload, headers):
        return self._request("POST", f"/ndt/safe-harbor-elections/{election_id}/notices", payload, headers)

    def list_notices_of_election(self, election_id, headers, params=None):
        return self._request("GET", f"/ndt/safe-harbor-elections/{election_id}/notice-list", headers=headers, params=params)

    def get_safe_harbor_notice(self, notice_id, headers):
        return self._request("GET", f"/ndt/safe-harbor-notices/{notice_id}", headers=headers)

    def distribute_safe_harbor_notice(self, notice_id, headers):
        return self._request("POST", f"/ndt/safe-harbor-notices/{notice_id}/distribute", {}, headers)

    def acknowledge_safe_harbor_notice(self, notice_id, headers):
        return self._request("POST", f"/ndt/safe-harbor-notices/{notice_id}/acknowledge", {}, headers)

    # --- Contribution ---
    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/ndt/contributions/{contribution_id}", headers=headers)

    def forfeit_contribution(self, contribution_id, headers):
        return self._request("POST", f"/ndt/contributions/{contribution_id}/forfeit", {}, headers)


api_client = ApiClient()
