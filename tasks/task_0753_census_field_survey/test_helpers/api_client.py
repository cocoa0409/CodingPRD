"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- SurveyProject ---
    def create_project(self, payload, headers):
        return self._request("POST", "/survey-projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/survey-projects/{project_id}", headers=headers)

    def open_project(self, project_id, headers):
        return self._request("POST", f"/survey-projects/{project_id}/open", headers=headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/survey-projects/{project_id}/close", headers=headers)

    # --- AssignmentArea ---
    def create_area(self, project_id, payload, headers):
        return self._request("POST", f"/survey-projects/{project_id}/assignment-areas", payload, headers)

    def list_areas(self, project_id, headers, params=None):
        return self._request("GET", f"/survey-projects/{project_id}/assignment-areas", headers=headers, params=params)

    def get_area(self, area_id, headers):
        return self._request("GET", f"/assignment-areas/{area_id}", headers=headers)

    def open_area(self, area_id, headers):
        return self._request("POST", f"/assignment-areas/{area_id}/open", headers=headers)

    def freeze_area(self, area_id, headers, payload=None):
        return self._request("POST", f"/assignment-areas/{area_id}/freeze", payload or {}, headers)

    def unfreeze_area(self, area_id, headers):
        return self._request("POST", f"/assignment-areas/{area_id}/unfreeze", headers=headers)

    def coverage_report(self, area_id, headers):
        return self._request("GET", f"/assignment-areas/{area_id}/coverage-report", headers=headers)

    # --- Case ---
    def create_case(self, area_id, payload, headers):
        return self._request("POST", f"/assignment-areas/{area_id}/cases", payload, headers)

    def list_cases(self, area_id, headers, params=None):
        return self._request("GET", f"/assignment-areas/{area_id}/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def create_assignment(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/assignments", payload, headers)

    def list_assignments(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/assignments", headers=headers, params=params)

    # --- Enumerator ---
    def create_enumerator(self, project_id, payload, headers):
        return self._request("POST", f"/survey-projects/{project_id}/enumerators", payload, headers)

    def list_enumerators(self, project_id, headers, params=None):
        return self._request("GET", f"/survey-projects/{project_id}/enumerators", headers=headers, params=params)

    def get_enumerator(self, enumerator_id, headers):
        return self._request("GET", f"/enumerators/{enumerator_id}", headers=headers)

    def hire_enumerator(self, enumerator_id, headers):
        return self._request("POST", f"/enumerators/{enumerator_id}/hire", headers=headers)

    def activate_enumerator(self, enumerator_id, headers):
        return self._request("POST", f"/enumerators/{enumerator_id}/activate", headers=headers)

    def suspend_enumerator(self, enumerator_id, headers, payload=None):
        return self._request("POST", f"/enumerators/{enumerator_id}/suspend", payload or {}, headers)

    def reinstate_enumerator(self, enumerator_id, headers):
        return self._request("POST", f"/enumerators/{enumerator_id}/reinstate", headers=headers)

    def list_enumerator_case_assignments(self, enumerator_id, headers, params=None):
        return self._request("GET", f"/enumerators/{enumerator_id}/case-assignments", headers=headers, params=params)

    def list_enumerator_pay_lines(self, enumerator_id, headers, params=None):
        return self._request("GET", f"/enumerators/{enumerator_id}/pay-lines", headers=headers, params=params)

    # --- Attempt ---
    def create_attempt(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/attempts", payload, headers)

    def list_attempts(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/attempts", headers=headers, params=params)

    def cancel_attempt(self, attempt_id, headers):
        return self._request("POST", f"/attempts/{attempt_id}/cancel", headers=headers)

    # --- Response ---
    def create_response(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/responses", payload, headers)

    def list_responses(self, case_id, headers, params=None):
        return self._request("GET", f"/cases/{case_id}/responses", headers=headers, params=params)

    def get_response(self, response_id, headers):
        return self._request("GET", f"/responses/{response_id}", headers=headers)

    # --- ReinterviewCase ---
    def create_reinterview(self, response_id, payload, headers):
        return self._request("POST", f"/responses/{response_id}/reinterviews", payload, headers)

    def list_reinterviews(self, response_id, headers, params=None):
        return self._request("GET", f"/responses/{response_id}/reinterviews", headers=headers, params=params)

    def get_reinterview(self, reinterview_id, headers):
        return self._request("GET", f"/reinterviews/{reinterview_id}", headers=headers)

    def start_reinterview(self, reinterview_id, headers):
        return self._request("POST", f"/reinterviews/{reinterview_id}/start", headers=headers)

    def finalize_reinterview(self, reinterview_id, payload, headers):
        return self._request("POST", f"/reinterviews/{reinterview_id}/finalize", payload, headers)

    # --- PayPeriod ---
    def create_pay_period(self, project_id, payload, headers):
        return self._request("POST", f"/survey-projects/{project_id}/pay-periods", payload, headers)

    def list_pay_periods(self, project_id, headers, params=None):
        return self._request("GET", f"/survey-projects/{project_id}/pay-periods", headers=headers, params=params)

    def get_pay_period(self, pay_period_id, headers):
        return self._request("GET", f"/pay-periods/{pay_period_id}", headers=headers)

    def lock_pay_period(self, pay_period_id, headers):
        return self._request("POST", f"/pay-periods/{pay_period_id}/lock", headers=headers)

    def pay_pay_period(self, pay_period_id, headers):
        return self._request("POST", f"/pay-periods/{pay_period_id}/pay", headers=headers)

    # --- PayLine ---
    def create_pay_line(self, pay_period_id, payload, headers):
        return self._request("POST", f"/pay-periods/{pay_period_id}/pay-lines", payload, headers)

    def list_pay_lines(self, pay_period_id, headers, params=None):
        return self._request("GET", f"/pay-periods/{pay_period_id}/pay-lines", headers=headers, params=params)

    def reverse_pay_line(self, pay_line_id, headers):
        return self._request("POST", f"/pay-lines/{pay_line_id}/reverse", headers=headers)


api_client = ApiClient()
