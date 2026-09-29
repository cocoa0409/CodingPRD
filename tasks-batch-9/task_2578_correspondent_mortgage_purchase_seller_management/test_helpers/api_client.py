"""Thin typed wrapper over the generic HTTP client, one method per endpoint."""

from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

BASE_PATH = "/correspondent"


class ApiClient(GenericApiClient):
    """One method per declared endpoint, all mounted under `/correspondent`."""

    # ─── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, current_utc: str, headers: dict) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: dict, headers: dict) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/_clock/set_current_utc", payload, headers
        )

    # ─── Products and pricing adjustments ───────────────────────────────────

    def create_product(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/products", payload, headers)

    def get_product(self, product_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/products/{product_id}", None, headers)

    def create_pricing_adjustment(
        self, product_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/products/{product_id}/pricing-adjustments",
            payload,
            headers,
        )

    def list_pricing_adjustments(
        self, product_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/products/{product_id}/pricing-adjustments",
            None,
            headers,
            params,
        )

    # ─── Sellers ────────────────────────────────────────────────────────────

    def create_seller(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/sellers", payload, headers)

    def get_seller(self, seller_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/sellers/{seller_id}", None, headers)

    def list_sellers(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/sellers", None, headers, params)

    # ─── Financial statements ───────────────────────────────────────────────

    def create_financial_statement(
        self, seller_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/sellers/{seller_id}/financial-statements",
            payload,
            headers,
        )

    def list_financial_statements(
        self, seller_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/sellers/{seller_id}/financial-statements",
            None,
            headers,
            params,
        )

    def review_financial_statement(
        self, statement_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/financial-statements/{statement_id}/review",
            payload,
            headers,
        )

    # ─── Quality control reviews ────────────────────────────────────────────

    def create_qc_review(
        self, seller_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/sellers/{seller_id}/qc-reviews", payload, headers
        )

    def list_qc_reviews(
        self, seller_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/sellers/{seller_id}/qc-reviews", None, headers, params
        )

    def complete_qc_review(
        self, qc_review_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/qc-reviews/{qc_review_id}/complete", payload, headers
        )

    # ─── Approval and standing ──────────────────────────────────────────────

    def decide_seller_approval(
        self, seller_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/sellers/{seller_id}/approval-decision",
            payload,
            headers,
        )

    def apply_standing_action(
        self, seller_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/sellers/{seller_id}/standing-actions",
            payload,
            headers,
        )

    # ─── Commitments ────────────────────────────────────────────────────────

    def create_commitment(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", f"{BASE_PATH}/commitments", payload, headers)

    def list_commitments(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/commitments", None, headers, params)

    def get_commitment(self, commitment_id: str, headers: dict) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/commitments/{commitment_id}", None, headers
        )

    def pair_off_commitment(
        self, commitment_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/commitments/{commitment_id}/pair-off", payload, headers
        )

    def expire_due_commitments(
        self, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/commitments/expire-due", payload, headers
        )

    # ─── Loan delivery and reads ────────────────────────────────────────────

    def deliver_loan(
        self, commitment_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/commitments/{commitment_id}/loans", payload, headers
        )

    def list_loans(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/loans", None, headers, params)

    def get_loan(self, loan_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"{BASE_PATH}/loans/{loan_id}", None, headers)

    def open_loan_review(
        self, loan_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/review", payload or {}, headers
        )

    # ─── Defects ────────────────────────────────────────────────────────────

    def create_defect(
        self, loan_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/defects", payload, headers
        )

    def list_defects(
        self, loan_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/loans/{loan_id}/defects", None, headers, params
        )

    def cure_defect(
        self, defect_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/defects/{defect_id}/cure", payload, headers
        )

    def waive_defect(
        self, defect_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/defects/{defect_id}/waive", payload, headers
        )

    # ─── Suspense conditions ────────────────────────────────────────────────

    def create_suspense_condition(
        self, loan_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/suspense-conditions", payload, headers
        )

    def list_suspense_conditions(
        self, loan_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/loans/{loan_id}/suspense-conditions",
            None,
            headers,
            params,
        )

    def clear_suspense_condition(
        self, condition_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/suspense-conditions/{condition_id}/clear",
            payload,
            headers,
        )

    def expire_loan_conditions(
        self, loan_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/loans/{loan_id}/expire-conditions",
            payload or {},
            headers,
        )

    # ─── Clearing, rejection, purchase advice ───────────────────────────────

    def clear_loan(
        self, loan_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/clear", payload or {}, headers
        )

    def reject_loan(
        self, loan_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/reject", payload or {}, headers
        )

    def create_purchase_advice(
        self, loan_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/purchase-advices", payload, headers
        )

    def list_purchase_advices(
        self, loan_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/loans/{loan_id}/purchase-advices",
            None,
            headers,
            params,
        )

    def settle_purchase_advice(
        self, advice_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/purchase-advices/{advice_id}/settle", payload, headers
        )

    def create_payment_event(
        self, loan_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/payment-events", payload, headers
        )

    # ─── Repurchase demands ─────────────────────────────────────────────────

    def create_repurchase_demand(
        self, loan_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/loans/{loan_id}/repurchase-demands", payload, headers
        )

    def list_loan_repurchase_demands(
        self, loan_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{BASE_PATH}/loans/{loan_id}/repurchase-demands",
            None,
            headers,
            params,
        )

    def list_repurchase_demands(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/repurchase-demands", None, headers, params
        )

    def get_repurchase_demand(self, demand_id: str, headers: dict) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/repurchase-demands/{demand_id}", None, headers
        )

    def appeal_repurchase_demand(
        self, demand_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/repurchase-demands/{demand_id}/appeal", payload, headers
        )

    def decide_repurchase_demand(
        self, demand_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/repurchase-demands/{demand_id}/decision",
            payload,
            headers,
        )

    def settle_repurchase_demand(
        self, demand_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/repurchase-demands/{demand_id}/settle", payload, headers
        )

    # ─── Escrow transfers ───────────────────────────────────────────────────

    def list_escrow_transfers(
        self, loan_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/loans/{loan_id}/escrow-transfers", None, headers, params
        )

    def complete_escrow_transfer(
        self, transfer_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/escrow-transfers/{transfer_id}/complete",
            payload,
            headers,
        )

    # ─── Scorecards ─────────────────────────────────────────────────────────

    def create_scorecard(
        self, seller_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE_PATH}/sellers/{seller_id}/scorecards", payload, headers
        )

    def list_scorecards(
        self, seller_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE_PATH}/sellers/{seller_id}/scorecards", None, headers, params
        )

    def close_scorecard(
        self, scorecard_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE_PATH}/scorecards/{scorecard_id}/close",
            payload or {},
            headers,
        )

    # ─── Raw escape hatch ───────────────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[dict] = None,
        headers: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> requests.Response:
        """Issue an arbitrary request under the API prefix."""
        return self._request(method, f"{BASE_PATH}{path}", payload, headers, params)


api_client = ApiClient()
