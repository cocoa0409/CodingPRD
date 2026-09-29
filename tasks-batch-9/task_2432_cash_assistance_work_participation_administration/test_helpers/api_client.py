"""Typed client with one method per endpoint of the API under test."""
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint; every method returns the raw response."""

    # --- Logical clock ------------------------------------------------------

    def set_clock(self, to_iso8601: str) -> requests.Response:
        """Move the logical clock. This endpoint takes no identity headers."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}
        )

    # --- Households ---------------------------------------------------------

    def register_household(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/households", payload, headers)

    def get_household(
        self, household_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_household_applications(
        self,
        household_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/households/{household_id}/applications",
            headers=headers,
            params=params,
        )

    def record_prior_assistance(
        self, household_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/households/{household_id}/prior-assistance-record",
            payload,
            headers,
        )

    # --- Applications -------------------------------------------------------

    def file_application(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/applications", payload, headers)

    def get_application(
        self, application_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def add_income_source(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/applications/{application_id}/income-sources", payload, headers
        )

    def list_income_sources(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/applications/{application_id}/income-sources",
            headers=headers,
            params=params,
        )

    def verify_income_source(
        self, income_source_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/income-sources/{income_source_id}/verify", payload, headers
        )

    def add_resource_item(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/applications/{application_id}/resource-items", payload, headers
        )

    def list_resource_items(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/applications/{application_id}/resource-items",
            headers=headers,
            params=params,
        )

    def determine_application(
        self,
        application_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/applications/{application_id}/determine", payload or {}, headers
        )

    def approve_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/applications/{application_id}/approve", payload, headers
        )

    def deny_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/applications/{application_id}/deny", payload, headers
        )

    def withdraw_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", payload, headers
        )

    # --- Diversion ----------------------------------------------------------

    def offer_diversion(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/applications/{application_id}/diversion-grants", payload, headers
        )

    def list_diversion_grants(
        self,
        application_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/applications/{application_id}/diversion-grants",
            headers=headers,
            params=params,
        )

    def accept_diversion(
        self,
        grant_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/diversion-grants/{grant_id}/accept", payload or {}, headers
        )

    def decline_diversion(
        self,
        grant_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/diversion-grants/{grant_id}/decline", payload or {}, headers
        )

    # --- Assistance cases ---------------------------------------------------

    def get_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def search_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", "/cases", headers=headers, params=params)

    def issue_month(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cases/{case_id}/issuances", payload, headers)

    def list_time_limit_months(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/cases/{case_id}/time-limit-months", headers=headers, params=params
        )

    # --- Hardship extensions ------------------------------------------------

    def request_extension(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/cases/{case_id}/extensions", payload, headers)

    def list_extensions(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/cases/{case_id}/extensions", headers=headers, params=params
        )

    def grant_extension(
        self, extension_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/extensions/{extension_id}/grant", payload, headers
        )

    def deny_extension(
        self, extension_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/extensions/{extension_id}/deny", payload, headers
        )

    def revoke_extension(
        self, extension_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/extensions/{extension_id}/revoke", payload, headers
        )

    # --- Work assignments ---------------------------------------------------

    def create_work_assignment(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/cases/{case_id}/work-assignments", payload, headers
        )

    def list_work_assignments(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/cases/{case_id}/work-assignments", headers=headers, params=params
        )

    def get_work_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/work-assignments/{assignment_id}", headers=headers
        )

    def activate_work_assignment(
        self,
        assignment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/work-assignments/{assignment_id}/activate",
            payload or {},
            headers,
        )

    def terminate_work_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/work-assignments/{assignment_id}/terminate", payload, headers
        )

    # --- Participation reports ----------------------------------------------

    def file_participation_report(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/work-assignments/{assignment_id}/participation-reports",
            payload,
            headers,
        )

    def list_participation_reports(
        self,
        assignment_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/work-assignments/{assignment_id}/participation-reports",
            headers=headers,
            params=params,
        )

    def verify_participation_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/participation-reports/{report_id}/verify", payload, headers
        )

    def reject_participation_report(
        self, report_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/participation-reports/{report_id}/reject", payload, headers
        )

    # --- Compliance episodes ------------------------------------------------

    def create_compliance_episode(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/compliance-episodes", payload, headers)

    def get_compliance_episode(
        self, episode_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/compliance-episodes/{episode_id}", headers=headers
        )

    def search_compliance_episodes(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/compliance-episodes", headers=headers, params=params
        )

    def start_conciliation(
        self,
        episode_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/compliance-episodes/{episode_id}/start-conciliation",
            payload or {},
            headers,
        )

    def grant_good_cause(
        self, episode_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/compliance-episodes/{episode_id}/grant-good-cause",
            payload,
            headers,
        )

    def resolve_compliant(
        self,
        episode_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/compliance-episodes/{episode_id}/resolve-compliant",
            payload or {},
            headers,
        )

    def impose_sanction(
        self,
        episode_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/compliance-episodes/{episode_id}/impose-sanction",
            payload or {},
            headers,
        )

    def begin_cure(
        self, episode_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/compliance-episodes/{episode_id}/begin-cure", payload, headers
        )

    # --- Supportive service authorizations ----------------------------------

    def create_supportive_authorization(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", "/supportive-service-authorizations", payload, headers
        )

    def get_supportive_authorization(
        self, authorization_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/supportive-service-authorizations/{authorization_id}",
            headers=headers,
        )

    def search_supportive_authorizations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/supportive-service-authorizations", headers=headers, params=params
        )

    def authorize_supportive(
        self,
        authorization_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/supportive-service-authorizations/{authorization_id}/authorize",
            payload or {},
            headers,
        )

    def void_supportive(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/supportive-service-authorizations/{authorization_id}/void",
            payload,
            headers,
        )

    def release_supportive_hold(
        self,
        authorization_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/supportive-service-authorizations/{authorization_id}/release-hold",
            payload or {},
            headers,
        )

    # --- Overpayments -------------------------------------------------------

    def draft_overpayment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/overpayments", payload, headers)

    def get_overpayment(
        self, overpayment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/overpayments/{overpayment_id}", headers=headers)

    def list_case_overpayments(
        self,
        case_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"/cases/{case_id}/overpayments", headers=headers, params=params
        )

    def establish_overpayment(
        self,
        overpayment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/overpayments/{overpayment_id}/establish",
            payload or {},
            headers,
        )

    def post_recovery_transaction(
        self, overpayment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/overpayments/{overpayment_id}/recovery-transactions",
            payload,
            headers,
        )

    def list_recovery_transactions(
        self,
        overpayment_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/overpayments/{overpayment_id}/recovery-transactions",
            headers=headers,
            params=params,
        )

    def write_off_overpayment(
        self, overpayment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/overpayments/{overpayment_id}/write-off", payload, headers
        )

    def refer_fraud(
        self, overpayment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/overpayments/{overpayment_id}/fraud-referral", payload, headers
        )

    def record_fraud_disposition(
        self, overpayment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/overpayments/{overpayment_id}/fraud-disposition", payload, headers
        )

    # --- Federal reporting periods ------------------------------------------

    def open_reporting_period(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reporting-periods", payload, headers)

    def get_reporting_period(
        self, period_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"/reporting-periods/{period_id}", headers=headers
        )

    def calculate_reporting_period(
        self,
        period_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/reporting-periods/{period_id}/calculate", payload or {}, headers
        )

    def certify_reporting_period(
        self,
        period_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/reporting-periods/{period_id}/certify", payload or {}, headers
        )
