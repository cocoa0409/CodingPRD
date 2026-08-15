"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4, §4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- cases ---
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def arrive_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/arrive", payload, headers)

    # --- household members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/members", headers=headers, params=params)

    # --- housing units ---
    def create_housing_unit(self, payload, headers):
        return self._request("POST", "/housing-units", payload, headers)

    def get_housing_unit(self, unit_id, headers):
        return self._request("GET", f"/housing-units/{unit_id}", headers=headers)

    # --- housing setups ---
    def create_housing_setup(self, payload, headers):
        return self._request("POST", "/housing-setups", payload, headers)

    def list_case_housing_setups(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/housing-setups", headers=headers, params=params)

    def list_unit_housing_setups(self, unit_id, headers, params=None):
        return self._request("GET", f"/housing-units/{unit_id}/housing-setups", headers=headers, params=params)

    def furnish_setup(self, setup_id, payload, headers):
        return self._request("POST", f"/housing-setups/{setup_id}/furnish", payload, headers)

    def ready_setup(self, setup_id, headers):
        return self._request("POST", f"/housing-setups/{setup_id}/ready", {}, headers)

    def vacate_setup(self, setup_id, headers):
        return self._request("POST", f"/housing-setups/{setup_id}/vacate", {}, headers)

    # --- service benchmarks ---
    def list_case_benchmarks(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/benchmarks", headers=headers, params=params)

    def get_benchmark(self, benchmark_id, headers):
        return self._request("GET", f"/benchmarks/{benchmark_id}", headers=headers)

    def list_benchmarks(self, headers, params=None):
        return self._request("GET", "/benchmarks", headers=headers, params=params)

    def fulfill_benchmark(self, benchmark_id, payload, headers):
        return self._request("POST", f"/benchmarks/{benchmark_id}/fulfill", payload, headers)

    def waive_benchmark(self, benchmark_id, payload, headers):
        return self._request("POST", f"/benchmarks/{benchmark_id}/waive", payload, headers)

    def rescind_benchmark(self, benchmark_id, headers):
        return self._request("POST", f"/benchmarks/{benchmark_id}/rescind", {}, headers)

    # --- benefit applications ---
    def create_benefit_application(self, payload, headers):
        return self._request("POST", "/benefit-applications", payload, headers)

    def get_benefit_application(self, application_id, headers):
        return self._request("GET", f"/benefit-applications/{application_id}", headers=headers)

    def list_benefit_applications(self, headers, params=None):
        return self._request("GET", "/benefit-applications", headers=headers, params=params)

    def transition_benefit_application(self, application_id, payload, headers):
        return self._request("POST", f"/benefit-applications/{application_id}/transition", payload, headers)

    # --- employment plans ---
    def create_employment_plan(self, payload, headers):
        return self._request("POST", "/employment-plans", payload, headers)

    def list_employment_plans(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/employment-plans", headers=headers, params=params)

    def patch_employment_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/employment-plans/{plan_id}", payload, headers)

    def certify_employment_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/employment-plans/{plan_id}/certify", payload, headers)

    # --- orientation sessions ---
    def create_orientation_session(self, payload, headers):
        return self._request("POST", "/orientation-sessions", payload, headers)

    def list_orientation_sessions(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/orientation-sessions", headers=headers, params=params)

    def complete_orientation_session(self, session_id, headers):
        return self._request("POST", f"/orientation-sessions/{session_id}/complete", {}, headers)

    # --- case notes ---
    def create_case_note(self, payload, headers):
        return self._request("POST", "/case-notes", payload, headers)

    def list_case_notes(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/case-notes", headers=headers, params=params)

    # --- case transfers ---
    def create_case_transfer(self, payload, headers):
        return self._request("POST", "/case-transfers", payload, headers)

    def list_case_transfers(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/case-transfers", headers=headers, params=params)

    def respond_case_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/case-transfers/{transfer_id}/respond", payload, headers)

    def withdraw_case_transfer(self, transfer_id, headers):
        return self._request("POST", f"/case-transfers/{transfer_id}/withdraw", {}, headers)

    # --- federal reports ---
    def create_federal_report(self, payload, headers):
        return self._request("POST", "/federal-reports", payload, headers)

    def get_federal_report(self, report_id, headers):
        return self._request("GET", f"/federal-reports/{report_id}", headers=headers)

    def submit_federal_report(self, report_id, headers):
        return self._request("POST", f"/federal-reports/{report_id}/submit", {}, headers)

    def review_federal_report(self, report_id, payload, headers):
        return self._request("POST", f"/federal-reports/{report_id}/review", payload, headers)


api_client = ApiClient()
