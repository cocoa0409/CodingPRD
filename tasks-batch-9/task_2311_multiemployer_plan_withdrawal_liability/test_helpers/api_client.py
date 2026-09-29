"""Typed HTTP client for the Multiemployer Plan Withdrawal Liability API.

One method per endpoint declared by the PRD. Collections live at the URL root
(there is no path prefix). Every method returns the raw `requests.Response` so
that callers can validate both success envelopes and error envelopes.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, exhaustive wrapper over the PRD's endpoint surface."""

    # ─── Plans ───────────────────────────────────────────────────────────────

    def create_plan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plans", payload, headers)

    def update_plan(self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/plans/{plan_id}", payload, headers)

    def get_plan(self, plan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plans/{plan_id}", None, headers)

    # ─── Controlled groups ───────────────────────────────────────────────────

    def create_controlled_group(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/controlled-groups", payload, headers)

    def get_controlled_group(self, controlled_group_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/controlled-groups/{controlled_group_id}", None, headers)

    # ─── Employers ───────────────────────────────────────────────────────────

    def create_employer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/employers", payload, headers)

    def list_employers(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/employers", None, headers, params)

    def get_employer(self, employer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/employers/{employer_id}", None, headers)

    def update_employer(self, employer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/employers/{employer_id}", payload, headers)

    # ─── Plan-year valuations ────────────────────────────────────────────────

    def create_plan_year_valuation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plan-year-valuations", payload, headers)

    def certify_plan_year_valuation(self, plan_year_valuation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/plan-year-valuations/{plan_year_valuation_id}/certify", {}, headers
        )

    def list_plan_year_valuations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/plan-year-valuations", None, headers, params)

    def get_plan_year_valuation(self, plan_year_valuation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/plan-year-valuations/{plan_year_valuation_id}", None, headers
        )

    # ─── Contribution records ────────────────────────────────────────────────

    def create_contribution_record(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/contribution-records", payload, headers)

    def list_contribution_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/contribution-records", None, headers, params)

    def get_contribution_record(self, contribution_record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/contribution-records/{contribution_record_id}", None, headers)

    # ─── Withdrawal events ───────────────────────────────────────────────────

    def create_withdrawal_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/withdrawal-events", payload, headers)

    def determine_withdrawal_event(self, withdrawal_event_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/withdrawal-events/{withdrawal_event_id}/determine", {}, headers
        )

    def list_withdrawal_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/withdrawal-events", None, headers, params)

    def get_withdrawal_event(self, withdrawal_event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/withdrawal-events/{withdrawal_event_id}", None, headers)

    # ─── Liability assessments ───────────────────────────────────────────────

    def create_liability_assessment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/liability-assessments", payload, headers)

    def issue_liability_assessment(self, liability_assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/liability-assessments/{liability_assessment_id}/issue", {}, headers
        )

    def list_liability_assessments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/liability-assessments", None, headers, params)

    def get_liability_assessment(self, liability_assessment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/liability-assessments/{liability_assessment_id}", None, headers
        )

    # ─── Payment schedules ───────────────────────────────────────────────────

    def create_payment_schedule(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/payment-schedules", payload, headers)

    def list_payment_schedules(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/payment-schedules", None, headers, params)

    def get_payment_schedule(self, payment_schedule_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/payment-schedules/{payment_schedule_id}", None, headers)

    def issue_default_notice(self, payment_schedule_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/payment-schedules/{payment_schedule_id}/default-notice", {}, headers
        )

    def cure_payment_schedule(
        self, payment_schedule_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/payment-schedules/{payment_schedule_id}/cure", payload, headers
        )

    def accelerate_payment_schedule(self, payment_schedule_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/payment-schedules/{payment_schedule_id}/accelerate", {}, headers
        )

    # ─── Instalments ─────────────────────────────────────────────────────────

    def list_installments(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/installments", None, headers, params)

    def get_installment(self, installment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/installments/{installment_id}", None, headers)

    def pay_installment(
        self, installment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/installments/{installment_id}/pay", payload, headers)

    # ─── Review requests ─────────────────────────────────────────────────────

    def create_review_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/review-requests", payload, headers)

    def decide_review_request(
        self, review_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/review-requests/{review_request_id}/decide", payload, headers
        )

    def list_review_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/review-requests", None, headers, params)

    def get_review_request(self, review_request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/review-requests/{review_request_id}", None, headers)

    # ─── Arbitrations ────────────────────────────────────────────────────────

    def create_arbitration(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/arbitrations", payload, headers)

    def advance_arbitration(
        self, arbitration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/arbitrations/{arbitration_id}/advance", payload, headers)

    def award_arbitration(
        self, arbitration_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/arbitrations/{arbitration_id}/award", payload, headers)

    def list_arbitrations(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/arbitrations", None, headers, params)

    def get_arbitration(self, arbitration_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/arbitrations/{arbitration_id}", None, headers)

    # ─── Asset-sale transactions ─────────────────────────────────────────────

    def create_asset_sale_transaction(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/asset-sale-transactions", payload, headers)

    def adjudicate_asset_sale_transaction(
        self, asset_sale_transaction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/asset-sale-transactions/{asset_sale_transaction_id}/adjudicate",
            payload,
            headers,
        )

    def list_asset_sale_transactions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/asset-sale-transactions", None, headers, params)

    def get_asset_sale_transaction(self, asset_sale_transaction_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/asset-sale-transactions/{asset_sale_transaction_id}", None, headers
        )

    # ─── Collection sweeps ───────────────────────────────────────────────────

    def run_collection_sweep(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/collection-sweeps", payload, headers)

    # ─── Logical clock ───────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
