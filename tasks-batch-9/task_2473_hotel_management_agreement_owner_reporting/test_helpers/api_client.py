"""One method per endpoint of the hotel-management API."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class ApiClient(GenericApiClient):
    """Typed access to every declared endpoint.

    Every method returns the raw ``requests.Response`` so tests can assert on
    the status code as well as the body.
    """

    # -- agreements ---------------------------------------------------------

    def create_agreement(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/agreements", payload, headers)

    def get_agreement(self, agreement_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/agreements/{agreement_id}", None, headers)

    def activate_agreement(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/activate", payload, headers
        )

    # -- budgets ------------------------------------------------------------

    def create_budget(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/budgets", payload, headers
        )

    def get_budget(self, budget_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/budgets/{budget_id}", None, headers)

    def list_budgets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/budgets", params, headers)

    def submit_budget(
        self,
        budget_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/budgets/{budget_id}/submit", payload, headers
        )

    def decide_budget(
        self, budget_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/budgets/{budget_id}/decision", payload, headers
        )

    # -- variance requests --------------------------------------------------

    def create_variance_request(
        self, budget_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/budgets/{budget_id}/variance-requests", payload, headers
        )

    def list_variance_requests(
        self,
        budget_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/budgets/{budget_id}/variance-requests", params, headers
        )

    def decide_variance_request(
        self, variance_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/variance-requests/{variance_id}/decision", payload, headers
        )

    # -- report packages ----------------------------------------------------

    def create_report_package(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/report-packages", payload, headers
        )

    def list_report_packages(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/agreements/{agreement_id}/report-packages", params, headers
        )

    def get_report_package(self, package_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/report-packages/{package_id}", None, headers)

    def submit_report_package(
        self,
        package_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/report-packages/{package_id}/submit", payload, headers
        )

    def review_report_package(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/report-packages/{package_id}/owner-review", payload, headers
        )

    # -- benchmarks ---------------------------------------------------------

    def create_benchmark(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/report-packages/{package_id}/benchmarks", payload, headers
        )

    def list_benchmarks(
        self,
        package_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/report-packages/{package_id}/benchmarks", params, headers
        )

    # -- centralized service charges ---------------------------------------

    def create_centralized_charge(
        self, package_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/report-packages/{package_id}/centralized-charges",
            payload,
            headers,
        )

    def list_centralized_charges(
        self,
        package_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/report-packages/{package_id}/centralized-charges",
            params,
            headers,
        )

    def review_centralized_charge(
        self, charge_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/centralized-charges/{charge_id}/review", payload, headers
        )

    # -- accruals, distributions, ledger -----------------------------------

    def list_fee_accruals(
        self,
        package_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/report-packages/{package_id}/fee-accruals", params, headers
        )

    def list_distributions(
        self,
        package_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/report-packages/{package_id}/distributions", params, headers
        )

    def execute_distribution(
        self,
        distribution_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/distributions/{distribution_id}/execute", payload, headers
        )

    def list_reserve_ledger(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/agreements/{agreement_id}/reserve-ledger", params, headers
        )

    # -- working capital calls ---------------------------------------------

    def create_working_capital_call(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/agreements/{agreement_id}/working-capital-calls",
            payload,
            headers,
        )

    def list_working_capital_calls(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/agreements/{agreement_id}/working-capital-calls",
            params,
            headers,
        )

    def fund_working_capital_call(
        self, call_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/working-capital-calls/{call_id}/fund", payload, headers
        )

    # -- true-up and performance tests -------------------------------------

    def run_annual_true_up(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/annual-true-up", payload, headers
        )

    def create_performance_test(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/agreements/{agreement_id}/performance-tests",
            payload,
            headers,
        )

    def list_performance_tests(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/agreements/{agreement_id}/performance-tests", params, headers
        )

    def cure_performance_test(
        self, test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/performance-tests/{test_id}/cure", payload, headers
        )

    def terminate_performance_test(
        self,
        test_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/performance-tests/{test_id}/terminate", payload, headers
        )

    # -- brand standard disputes -------------------------------------------

    def create_brand_dispute(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/brand-disputes", payload, headers
        )

    def list_brand_disputes(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/agreements/{agreement_id}/brand-disputes", params, headers
        )

    def advance_brand_dispute(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/brand-disputes/{dispute_id}/rounds", payload, headers
        )

    # -- employment claims --------------------------------------------------

    def create_employment_claim(
        self, agreement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/agreements/{agreement_id}/employment-claims",
            payload,
            headers,
        )

    def list_employment_claims(
        self,
        agreement_id: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/agreements/{agreement_id}/employment-claims", params, headers
        )

    def allocate_employment_claim(
        self, claim_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/employment-claims/{claim_id}/allocation", payload, headers
        )

    # -- logical clock ------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]
