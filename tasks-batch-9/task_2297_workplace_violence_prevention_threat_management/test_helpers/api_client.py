"""One method per endpoint of the workplace-violence prevention API."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed access to every endpoint, returning the raw HTTP response."""

    # ------------------------------------------------------------------
    # Worksites
    # ------------------------------------------------------------------

    def create_worksite(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/worksites", payload, headers)

    def get_worksite(self, worksite_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/worksites/{worksite_id}", None, headers)

    def list_worksites(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/worksites", params, headers)

    # ------------------------------------------------------------------
    # Work areas
    # ------------------------------------------------------------------

    def create_work_area(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/work-areas", payload, headers)

    def get_work_area(self, work_area_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/work-areas/{work_area_id}", None, headers)

    def list_work_areas(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/work-areas", params, headers)

    # ------------------------------------------------------------------
    # Prevention plans
    # ------------------------------------------------------------------

    def create_prevention_plan(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/prevention-plans", payload, headers)

    def get_prevention_plan(self, plan_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/prevention-plans/{plan_id}", None, headers)

    def list_prevention_plans(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/prevention-plans", params, headers)

    def submit_prevention_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/prevention-plans/{plan_id}/submit", payload, headers)

    def return_prevention_plan_for_revision(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/prevention-plans/{plan_id}/return-for-revision", payload, headers
        )

    def activate_prevention_plan(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/prevention-plans/{plan_id}/activate", payload, headers)

    # ------------------------------------------------------------------
    # Hazard assessments
    # ------------------------------------------------------------------

    def create_hazard_assessment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/hazard-assessments", payload, headers)

    def get_hazard_assessment(
        self, hazard_assessment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/hazard-assessments/{hazard_assessment_id}", None, headers)

    def list_hazard_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/hazard-assessments", params, headers)

    def validate_hazard_assessment(
        self, hazard_assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/hazard-assessments/{hazard_assessment_id}/validate", payload, headers
        )

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------

    def create_employee(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/employees/{employee_id}", None, headers)

    def list_employees(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/employees", params, headers)

    def separate_employee(
        self, employee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/employees/{employee_id}/separate", payload, headers)

    # ------------------------------------------------------------------
    # Training modules
    # ------------------------------------------------------------------

    def create_training_module(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/training-modules", payload, headers)

    def get_training_module(self, module_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/training-modules/{module_id}", None, headers)

    def list_training_modules(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/training-modules", params, headers)

    # ------------------------------------------------------------------
    # Training assignments
    # ------------------------------------------------------------------

    def create_training_assignment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/training-assignments", payload, headers)

    def get_training_assignment(
        self, training_assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/training-assignments/{training_assignment_id}", None, headers)

    def list_training_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/training-assignments", params, headers)

    def complete_training_assignment(
        self, training_assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/training-assignments/{training_assignment_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------

    def create_incident_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/incident-reports", payload, headers)

    def get_incident_report(
        self, incident_report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/incident-reports/{incident_report_id}", None, headers)

    def list_incident_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/incident-reports", params, headers)

    def triage_incident_report(
        self, incident_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/incident-reports/{incident_report_id}/triage", payload, headers
        )

    def create_retaliation_update(
        self, incident_report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/incident-reports/{incident_report_id}/retaliation-updates", payload, headers
        )

    # ------------------------------------------------------------------
    # Threat cases
    # ------------------------------------------------------------------

    def create_threat_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/threat-cases", payload, headers)

    def get_threat_case(self, threat_case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/threat-cases/{threat_case_id}", None, headers)

    def list_threat_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/threat-cases", params, headers)

    def create_team_assignment(
        self, threat_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/threat-cases/{threat_case_id}/team-assignments", payload, headers
        )

    def convene_threat_case(
        self, threat_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/threat-cases/{threat_case_id}/convene", payload, headers)

    def cast_ballot(
        self, threat_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/threat-cases/{threat_case_id}/ballots", payload, headers)

    def reassess_threat_case(
        self, threat_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/threat-cases/{threat_case_id}/reassess", payload, headers)

    def decide_threat_case(
        self, threat_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/threat-cases/{threat_case_id}/decide", payload, headers)

    def close_threat_case(
        self, threat_case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/threat-cases/{threat_case_id}/close", payload, headers)

    # ------------------------------------------------------------------
    # Team assignments
    # ------------------------------------------------------------------

    def get_team_assignment(
        self, team_assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/team-assignments/{team_assignment_id}", None, headers)

    def list_team_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/team-assignments", params, headers)

    # ------------------------------------------------------------------
    # Case actions
    # ------------------------------------------------------------------

    def create_case_action(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/case-actions", payload, headers)

    def get_case_action(self, case_action_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/case-actions/{case_action_id}", None, headers)

    def list_case_actions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/case-actions", params, headers)

    def revoke_case_action(
        self, case_action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/case-actions/{case_action_id}/revoke", payload, headers)

    def complete_case_action(
        self, case_action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/case-actions/{case_action_id}/complete", payload, headers)

    # ------------------------------------------------------------------
    # Violent incident log
    # ------------------------------------------------------------------

    def get_log_entry(self, log_entry_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/violent-incident-log/{log_entry_id}", None, headers)

    def list_log_entries(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/violent-incident-log", params, headers)

    def amend_log_entry(
        self, log_entry_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/violent-incident-log/{log_entry_id}/amendments", payload, headers
        )

    # ------------------------------------------------------------------
    # Drills
    # ------------------------------------------------------------------

    def create_drill(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/drills", payload, headers)

    def get_drill(self, drill_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/drills/{drill_id}", None, headers)

    def list_drills(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/drills", params, headers)

    def execute_drill(
        self, drill_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/drills/{drill_id}/execute", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock and nightly sweep
    # ------------------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def daily_run(self, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None) -> requests.Response:
        return self._request("POST", "/_ops/daily-run", payload or {}, headers)


#: Shared client instance; the server lifecycle is managed by the harness.
api_client = ApiClient()
