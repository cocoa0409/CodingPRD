"""One typed method per endpoint of the Money Transmitter Licensing API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as on bodies. Paths, methods and body field names are
transcribed from PRD section 4 and the workflow narratives of section 3.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class MoneyTransmitterApiClient(GenericApiClient):
    """Thin transport wrapper: no validation, no retries, no state."""

    # -----------------------------------------------------------------
    # Administrative clock
    # -----------------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload=payload, headers=headers)

    # -----------------------------------------------------------------
    # Jurisdictions
    # -----------------------------------------------------------------

    def create_jurisdiction(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/jurisdictions", payload=payload, headers=headers)

    # -----------------------------------------------------------------
    # Licensees
    # -----------------------------------------------------------------

    def create_licensee(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/licensees", payload=payload, headers=headers)

    def get_licensee(self, licensee_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/licensees/{licensee_id}", headers=headers)

    def update_licensee_financials(
        self, licensee_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/licensees/{licensee_id}/financials", payload=payload, headers=headers
        )

    def get_coverage_summary(self, licensee_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/licensees/{licensee_id}/coverage-summary", headers=headers)

    def get_assessment_summary(
        self, licensee_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/licensees/{licensee_id}/assessment-summary", headers=headers)

    def list_licensee_investment_holdings(
        self,
        licensee_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/licensees/{licensee_id}/investment-holdings", headers=headers, params=params
        )

    # -----------------------------------------------------------------
    # Control persons
    # -----------------------------------------------------------------

    def create_control_person(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/control-persons", payload=payload, headers=headers)

    def get_control_person(
        self, control_person_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/control-persons/{control_person_id}", headers=headers)

    def list_control_persons(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/control-persons", headers=headers, params=params)

    def adjudicate_background_check(
        self, control_person_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/control-persons/{control_person_id}/background-check-adjudication",
            payload=payload,
            headers=headers,
        )

    def decide_change_of_control(
        self, control_person_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/control-persons/{control_person_id}/change-of-control-decisions",
            payload=payload,
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Licence applications
    # -----------------------------------------------------------------

    def create_application(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/license-applications", payload=payload, headers=headers)

    def get_application(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/license-applications/{application_id}", headers=headers)

    def list_applications(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/license-applications", headers=headers, params=params)

    def submit_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/license-applications/{application_id}/submit",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def review_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/license-applications/{application_id}/review-actions",
            payload=payload,
            headers=headers,
        )

    def resubmit_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/license-applications/{application_id}/resubmit",
            payload=payload,
            headers=headers,
        )

    # -----------------------------------------------------------------
    # State licences
    # -----------------------------------------------------------------

    def get_state_license(self, license_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/state-licenses/{license_id}", headers=headers)

    def list_state_licenses(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/state-licenses", headers=headers, params=params)

    def post_bond(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/state-licenses/{license_id}/bond", payload=payload, headers=headers
        )

    def file_bond_cancellation_notice(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/state-licenses/{license_id}/bond-cancellation-notice",
            payload=payload,
            headers=headers,
        )

    def adjust_obligations(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"/state-licenses/{license_id}/obligations",
            payload=payload,
            headers=headers,
        )

    def renew_license(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/state-licenses/{license_id}/renewals", payload=payload, headers=headers
        )

    def request_surrender(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/state-licenses/{license_id}/surrender-requests",
            payload=payload,
            headers=headers,
        )

    def decide_surrender(
        self, license_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/state-licenses/{license_id}/surrender-decisions",
            payload=payload,
            headers=headers,
        )

    def list_license_call_reports(
        self,
        license_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/state-licenses/{license_id}/call-reports", headers=headers, params=params
        )

    # -----------------------------------------------------------------
    # Call reports
    # -----------------------------------------------------------------

    def file_call_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/call-reports", payload=payload, headers=headers)

    # -----------------------------------------------------------------
    # Delegates
    # -----------------------------------------------------------------

    def create_delegate(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/delegates", payload=payload, headers=headers)

    def get_delegate(self, delegate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/delegates/{delegate_id}", headers=headers)

    def list_delegates(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/delegates", headers=headers, params=params)

    def submit_oversight_review(
        self, delegate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/delegates/{delegate_id}/oversight-reviews",
            payload=payload,
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Delegate authorizations
    # -----------------------------------------------------------------

    def create_delegate_authorization(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/delegate-authorizations", payload=payload, headers=headers)

    def get_delegate_authorization(
        self, authorization_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/delegate-authorizations/{authorization_id}", headers=headers)

    def list_delegate_authorizations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/delegate-authorizations", headers=headers, params=params)

    def activate_authorization(
        self,
        authorization_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/delegate-authorizations/{authorization_id}/activate",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def terminate_authorization(
        self,
        authorization_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/delegate-authorizations/{authorization_id}/terminate",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Investment holdings
    # -----------------------------------------------------------------

    def create_investment_holding(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/investment-holdings", payload=payload, headers=headers)

    def dispose_investment_holding(
        self,
        holding_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/investment-holdings/{holding_id}/dispose",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Permissible investment tests
    # -----------------------------------------------------------------

    def create_investment_test(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/permissible-investment-tests", payload=payload, headers=headers
        )

    def prepare_investment_test(
        self,
        test_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/permissible-investment-tests/{test_id}/prepare",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def certify_investment_test(
        self,
        test_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/permissible-investment-tests/{test_id}/certify",
            payload=payload if payload is not None else {},
            headers=headers,
        )

    def get_investment_test(self, test_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/permissible-investment-tests/{test_id}", headers=headers)

    def list_investment_tests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/permissible-investment-tests", headers=headers, params=params
        )

    # -----------------------------------------------------------------
    # Multistate examinations
    # -----------------------------------------------------------------

    def create_exam(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/multistate-exams", payload=payload, headers=headers)

    def get_exam(self, exam_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/multistate-exams/{exam_id}", headers=headers)

    def list_exams(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/multistate-exams", headers=headers, params=params)

    def change_exam_status(
        self, exam_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/multistate-exams/{exam_id}/status-changes",
            payload=payload,
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Information requests
    # -----------------------------------------------------------------

    def create_information_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/information-requests", payload=payload, headers=headers)

    def get_information_request(
        self, request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/information-requests/{request_id}", headers=headers)

    def list_information_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/information-requests", headers=headers, params=params)

    def respond_to_information_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/information-requests/{request_id}/response",
            payload=payload,
            headers=headers,
        )

    def disposition_information_request(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/information-requests/{request_id}/disposition",
            payload=payload,
            headers=headers,
        )

    # -----------------------------------------------------------------
    # Enforcement actions
    # -----------------------------------------------------------------

    def create_enforcement_action(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/enforcement-actions", payload=payload, headers=headers)

    def get_enforcement_action(self, action_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/enforcement-actions/{action_id}", headers=headers)

    def list_enforcement_actions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/enforcement-actions", headers=headers, params=params)

    def respond_to_enforcement_action(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enforcement-actions/{action_id}/responses",
            payload=payload,
            headers=headers,
        )

    def resolve_enforcement_action(
        self, action_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/enforcement-actions/{action_id}/resolutions",
            payload=payload,
            headers=headers,
        )
