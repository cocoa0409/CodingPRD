"""One method per declared endpoint of the merchant-underwriting API.

Every method returns the raw ``requests.Response`` so that tests can assert on
status codes as well as bodies. Paths carry no prefix.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint surface of the merchant underwriting / portfolio risk API."""

    # -- logical clock ------------------------------------------------------

    def set_clock(self, now_utc: str, headers: dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", {"now_utc": now_utc}, headers)

    # -- prohibited category rules ----------------------------------------

    def create_category_rule(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/prohibited-category-rules", payload, headers)

    def list_category_rules(self, headers, **params) -> requests.Response:
        return self._request("GET", "/prohibited-category-rules", params or None, headers)

    # -- merchant applications --------------------------------------------

    def create_application(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/merchant-applications", payload, headers)

    def get_application(self, application_id: str, headers) -> requests.Response:
        return self._request("GET", f"/merchant-applications/{application_id}", None, headers)

    def list_applications(self, headers, **params) -> requests.Response:
        return self._request("GET", "/merchant-applications", params or None, headers)

    def list_superseding_applications(self, application_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET",
            f"/merchant-applications/{application_id}/superseding-applications",
            params or None,
            headers,
        )

    def submit_application(self, application_id: str, headers) -> requests.Response:
        return self._request("POST", f"/merchant-applications/{application_id}/submit", {}, headers)

    def request_application_info(
        self, application_id: str, outstanding_info_items: list[str], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/merchant-applications/{application_id}/request-info",
            {"outstanding_info_items": outstanding_info_items},
            headers,
        )

    def withdraw_application(self, application_id: str, headers) -> requests.Response:
        return self._request("POST", f"/merchant-applications/{application_id}/withdraw", {}, headers)

    def advance_to_underwriting(
        self, application_id: str, headers, payload: Optional[dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/merchant-applications/{application_id}/advance-to-underwriting",
            payload if payload is not None else {},
            headers,
        )

    def decide_application(self, application_id: str, payload: dict[str, Any], headers) -> requests.Response:
        return self._request(
            "POST", f"/merchant-applications/{application_id}/decision", payload, headers
        )

    def list_onboarded_merchants(self, application_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET",
            f"/merchant-applications/{application_id}/onboarded-merchants",
            params or None,
            headers,
        )

    # -- beneficial owners -------------------------------------------------

    def create_beneficial_owner(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/beneficial-owners", payload, headers)

    def list_beneficial_owners(self, application_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET",
            f"/merchant-applications/{application_id}/beneficial-owners",
            params or None,
            headers,
        )

    def screen_beneficial_owner(self, owner_id: str, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"/beneficial-owners/{owner_id}/screen", payload, headers)

    # -- business verifications -------------------------------------------

    def create_business_verification(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/business-verifications", payload, headers)

    def list_business_verifications(self, application_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET",
            f"/merchant-applications/{application_id}/business-verifications",
            params or None,
            headers,
        )

    # -- credit assessments -----------------------------------------------

    def create_credit_assessment(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/credit-assessments", payload, headers)

    def list_credit_assessments(self, application_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET",
            f"/merchant-applications/{application_id}/credit-assessments",
            params or None,
            headers,
        )

    # -- merchants ---------------------------------------------------------

    def get_merchant(self, merchant_id: str, headers) -> requests.Response:
        return self._request("GET", f"/merchants/{merchant_id}", None, headers)

    def list_merchants(self, headers, **params) -> requests.Response:
        return self._request("GET", "/merchants", params or None, headers)

    def get_risk_summary(self, merchant_id: str, headers) -> requests.Response:
        return self._request("GET", f"/merchants/{merchant_id}/risk-summary", None, headers)

    def list_merchant_reserve_accounts(self, merchant_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/merchants/{merchant_id}/reserve-accounts", params or None, headers
        )

    # -- day activity ------------------------------------------------------

    def create_day_activity(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/merchant-day-activity", payload, headers)

    def list_day_activity(self, merchant_id: str, headers, **params) -> requests.Response:
        return self._request("GET", f"/merchants/{merchant_id}/day-activity", params or None, headers)

    # -- monitoring --------------------------------------------------------

    def create_monitoring_run(self, as_of_date: str, headers) -> requests.Response:
        return self._request("POST", "/monitoring-runs", {"as_of_date": as_of_date}, headers)

    def list_monitoring_alerts(self, merchant_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/merchants/{merchant_id}/monitoring-alerts", params or None, headers
        )

    def review_alert(self, alert_id: str, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"/monitoring-alerts/{alert_id}/review", payload, headers)

    # -- funding holds -----------------------------------------------------

    def place_funding_hold(self, merchant_id: str, reason_code: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/merchants/{merchant_id}/funding-holds", {"reason_code": reason_code}, headers
        )

    def release_funding_hold(self, merchant_id: str, headers) -> requests.Response:
        return self._request("POST", f"/merchants/{merchant_id}/funding-release", {}, headers)

    # -- settlement batches ------------------------------------------------

    def create_settlement_batch(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/settlement-batches", payload, headers)

    def get_settlement_batch(self, batch_id: str, headers) -> requests.Response:
        return self._request("GET", f"/settlement-batches/{batch_id}", None, headers)

    def list_merchant_settlement_batches(self, merchant_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/merchants/{merchant_id}/settlement-batches", params or None, headers
        )

    def pay_settlement_batch(self, batch_id: str, headers) -> requests.Response:
        return self._request("POST", f"/settlement-batches/{batch_id}/pay", {}, headers)

    def reverse_settlement_batch(self, batch_id: str, reversal_reason_code: str, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/settlement-batches/{batch_id}/reverse",
            {"reversal_reason_code": reversal_reason_code},
            headers,
        )

    def list_batch_ledger_entries(self, batch_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/settlement-batches/{batch_id}/ledger-entries", params or None, headers
        )

    # -- reserve accounts --------------------------------------------------

    def get_reserve_account(self, reserve_account_id: str, headers) -> requests.Response:
        return self._request("GET", f"/reserve-accounts/{reserve_account_id}", None, headers)

    def list_reserve_accounts(self, headers, **params) -> requests.Response:
        return self._request("GET", "/reserve-accounts", params or None, headers)

    def list_reserve_ledger_entries(self, reserve_account_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/reserve-accounts/{reserve_account_id}/ledger-entries", params or None, headers
        )

    def create_release_request(
        self, reserve_account_id: str, payload: dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/reserve-accounts/{reserve_account_id}/release-requests", payload, headers
        )

    # -- remediation programs ---------------------------------------------

    def create_remediation_program(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/remediation-programs", payload, headers)

    def activate_remediation_program(self, program_id: str, headers) -> requests.Response:
        return self._request("POST", f"/remediation-programs/{program_id}/activate", {}, headers)

    def evaluate_remediation_month(self, program_id: str, month_index: int, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/remediation-programs/{program_id}/evaluate-month",
            {"month_index": month_index},
            headers,
        )

    def get_remediation_program(self, program_id: str, headers) -> requests.Response:
        return self._request("GET", f"/remediation-programs/{program_id}", None, headers)

    def list_merchant_remediation_programs(self, merchant_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/merchants/{merchant_id}/remediation-programs", params or None, headers
        )

    # -- termination decisions --------------------------------------------

    def create_termination_decision(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/termination-decisions", payload, headers)

    def approve_termination_decision(self, decision_id: str, headers) -> requests.Response:
        return self._request("POST", f"/termination-decisions/{decision_id}/approve", {}, headers)

    def reject_termination_decision(self, decision_id: str, rejection_note: str, headers) -> requests.Response:
        return self._request(
            "POST",
            f"/termination-decisions/{decision_id}/reject",
            {"rejection_note": rejection_note},
            headers,
        )

    def execute_termination_decision(self, decision_id: str, headers) -> requests.Response:
        return self._request("POST", f"/termination-decisions/{decision_id}/execute", {}, headers)

    def get_termination_decision(self, decision_id: str, headers) -> requests.Response:
        return self._request("GET", f"/termination-decisions/{decision_id}", None, headers)

    def list_merchant_termination_decisions(self, merchant_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/merchants/{merchant_id}/termination-decisions", params or None, headers
        )

    # -- appeals -----------------------------------------------------------

    def create_appeal(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/appeals", payload, headers)

    def review_appeal(self, appeal_id: str, headers) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/review", {}, headers)

    def request_appeal_info(self, appeal_id: str, outstanding_info_items: list[str], headers) -> requests.Response:
        return self._request(
            "POST",
            f"/appeals/{appeal_id}/request-info",
            {"outstanding_info_items": outstanding_info_items},
            headers,
        )

    def respond_to_appeal_info(self, appeal_id: str, response_text: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/appeals/{appeal_id}/respond", {"response_text": response_text}, headers
        )

    def decide_appeal(self, appeal_id: str, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    def get_appeal(self, appeal_id: str, headers) -> requests.Response:
        return self._request("GET", f"/appeals/{appeal_id}", None, headers)

    def list_merchant_appeals(self, merchant_id: str, headers, **params) -> requests.Response:
        return self._request("GET", f"/merchants/{merchant_id}/appeals", params or None, headers)

    def list_decision_appeals(self, decision_id: str, headers, **params) -> requests.Response:
        return self._request(
            "GET", f"/termination-decisions/{decision_id}/appeals", params or None, headers
        )

    # -- portfolio forecasts ----------------------------------------------

    def create_portfolio_forecast(self, payload: dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/portfolio-forecasts", payload, headers)

    def get_portfolio_forecast(self, forecast_id: str, headers) -> requests.Response:
        return self._request("GET", f"/portfolio-forecasts/{forecast_id}", None, headers)

    def list_portfolio_forecasts(self, headers, **params) -> requests.Response:
        return self._request("GET", "/portfolio-forecasts", params or None, headers)


#: Shared client instance; the base URL comes from API_BASE_URL.
api_client = ApiClient()
