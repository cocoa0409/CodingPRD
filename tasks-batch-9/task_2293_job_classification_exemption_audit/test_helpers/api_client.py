"""HTTP client with one method per endpoint of the classification audit API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per documented endpoint; every method returns the raw response."""

    # -- logical clock ----------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- state rules ------------------------------------------------------
    def create_state_rule(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/state-rules", payload, headers)

    def list_state_rules(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/state-rules", params, headers)

    # -- audit projects ---------------------------------------------------
    def create_audit_project(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/audit-projects", payload, headers)

    def get_audit_project(self, project_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/audit-projects/{project_id}", None, headers)

    def set_audit_project_status(
        self, project_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/audit-projects/{project_id}/status", payload, headers)

    def list_project_job_families(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/audit-projects/{project_id}/job-families", params, headers)

    def list_project_contractor_reviews(
        self, project_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/audit-projects/{project_id}/contractor-reviews", params, headers
        )

    # -- job families -----------------------------------------------------
    def create_job_family(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/job-families", payload, headers)

    def get_job_family(self, family_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/job-families/{family_id}", None, headers)

    def list_child_families(
        self, family_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/job-families/{family_id}/child-families", params, headers)

    def list_family_positions(
        self, family_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/job-families/{family_id}/positions", params, headers)

    # -- positions --------------------------------------------------------
    def create_position(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/positions", payload, headers)

    def get_position(self, position_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/positions/{position_id}", None, headers)

    def list_position_duty_statements(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/positions/{position_id}/duty-statements", params, headers)

    def list_position_interviews(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"/positions/{position_id}/interviews", params, headers)

    def list_position_exemption_analyses(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/positions/{position_id}/exemption-analyses", params, headers
        )

    def list_position_reclassification_cases(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/positions/{position_id}/reclassification-cases", params, headers
        )

    def list_position_job_change_triggers(
        self, position_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/positions/{position_id}/job-change-triggers", params, headers
        )

    # -- duty statements --------------------------------------------------
    def create_duty_statement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/duty-statements", payload, headers)

    # -- interviews -------------------------------------------------------
    def create_interview(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/interviews", payload, headers)

    def get_interview(self, interview_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/interviews/{interview_id}", None, headers)

    def complete_interview(
        self, interview_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/interviews/{interview_id}/complete", payload, headers)

    def attest_interview(
        self, interview_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("POST", f"/interviews/{interview_id}/attest", payload or {}, headers)

    def void_interview(
        self, interview_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/interviews/{interview_id}/void", payload, headers)

    # -- exemption analyses ----------------------------------------------
    def create_exemption_analysis(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/exemption-analyses", payload, headers)

    def get_exemption_analysis(self, analysis_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/exemption-analyses/{analysis_id}", None, headers)

    def submit_exemption_analysis(
        self, analysis_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/exemption-analyses/{analysis_id}/submit", payload or {}, headers
        )

    def return_exemption_analysis(
        self, analysis_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/exemption-analyses/{analysis_id}/return", payload, headers
        )

    def determine_exemption_analysis(
        self, analysis_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/exemption-analyses/{analysis_id}/determine", payload or {}, headers
        )

    # -- reclassification cases -------------------------------------------
    def create_reclassification_case(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reclassification-cases", payload, headers)

    def get_reclassification_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reclassification-cases/{case_id}", None, headers)

    def convert_pay(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/reclassification-cases/{case_id}/pay-conversion", payload, headers
        )

    def revert_pay_conversion(
        self, case_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/reclassification-cases/{case_id}/revert-pay-conversion",
            payload or {},
            headers,
        )

    def case_communication(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/reclassification-cases/{case_id}/communication", payload, headers
        )

    def list_case_back_wage_estimates(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/reclassification-cases/{case_id}/back-wage-estimates", params, headers
        )

    def list_case_voluntary_corrections(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/reclassification-cases/{case_id}/voluntary-corrections", params, headers
        )

    # -- back wage estimates ----------------------------------------------
    def create_back_wage_estimate(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/back-wage-estimates", payload, headers)

    # -- voluntary corrections --------------------------------------------
    def create_voluntary_correction(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/voluntary-corrections", payload, headers)

    def decide_voluntary_correction(
        self, correction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/voluntary-corrections/{correction_id}/decision", payload, headers
        )

    # -- contractor reviews ------------------------------------------------
    def create_contractor_review(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/contractor-reviews", payload, headers)

    def finalize_contractor_review(
        self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/contractor-reviews/{review_id}/finalize", payload, headers
        )

    # -- job change triggers ------------------------------------------------
    def create_job_change_trigger(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/job-change-triggers", payload, headers)


api_client = ApiClient()
