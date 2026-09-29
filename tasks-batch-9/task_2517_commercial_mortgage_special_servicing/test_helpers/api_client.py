"""Endpoint client for the CMBS Special Servicing API.

One method per endpoint declared by the PRD. Every method returns the raw
``requests.Response`` so tests can assert on HTTP status as well as body.
"""

from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .types import Headers, Json

BASE = "/special-servicing"


class SpecialServicingClient(GenericApiClient):
    """Thin, complete binding of the PRD's endpoint table."""

    # ------------------------------------------------------------------
    # Trust
    # ------------------------------------------------------------------
    def create_trust(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE}/trusts", payload, headers)

    def get_trust(self, trust_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE}/trusts/{trust_id}", None, headers)

    def list_trusts(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/trusts", params, headers)

    # ------------------------------------------------------------------
    # Loan
    # ------------------------------------------------------------------
    def create_loan(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE}/loans", payload, headers)

    def get_loan(self, loan_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE}/loans/{loan_id}", None, headers)

    def list_loans(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/loans", params, headers)

    def set_loan_servicing_status(
        self, loan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/servicing-status", payload, headers
        )

    def set_loan_payment_status(
        self, loan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/loans/{loan_id}/payment-status", payload, headers
        )

    def get_asset_business_plan(
        self, loan_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/loans/{loan_id}/asset-business-plan", None, headers
        )

    # ------------------------------------------------------------------
    # ServicingTransferEvent
    # ------------------------------------------------------------------
    def create_transfer_event(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/transfer-events", payload, headers)

    def get_transfer_event(
        self, event_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/transfer-events/{event_id}", None, headers
        )

    def list_loan_transfer_events(
        self, loan_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/loans/{loan_id}/transfer-events", params, headers
        )

    # ------------------------------------------------------------------
    # BorrowerRequest
    # ------------------------------------------------------------------
    def create_borrower_request(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/borrower-requests", payload, headers)

    def get_borrower_request(
        self, request_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/borrower-requests/{request_id}", None, headers
        )

    def list_borrower_requests(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/borrower-requests", params, headers)

    def record_borrower_request_analysis(
        self, request_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/borrower-requests/{request_id}/analysis", payload, headers
        )

    def set_borrower_request_status(
        self, request_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/borrower-requests/{request_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Appraisal
    # ------------------------------------------------------------------
    def create_appraisal(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE}/appraisals", payload, headers)

    def get_appraisal(self, appraisal_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE}/appraisals/{appraisal_id}", None, headers)

    def list_appraisals(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/appraisals", params, headers)

    def set_appraisal_status(
        self, appraisal_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/appraisals/{appraisal_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # AppraisalReduction
    # ------------------------------------------------------------------
    def get_appraisal_reduction(
        self, reduction_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/appraisal-reductions/{reduction_id}", None, headers
        )

    def list_appraisal_reductions(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/appraisal-reductions", params, headers)

    def set_appraisal_reduction_status(
        self, reduction_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/appraisal-reductions/{reduction_id}/status",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Advance
    # ------------------------------------------------------------------
    def create_advance(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE}/advances", payload, headers)

    def get_advance(self, advance_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE}/advances/{advance_id}", None, headers)

    def list_advances(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/advances", params, headers)

    def set_advance_status(
        self, advance_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/advances/{advance_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # WorkoutPlan
    # ------------------------------------------------------------------
    def create_workout_plan(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/workout-plans", payload, headers)

    def get_workout_plan(self, plan_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE}/workout-plans/{plan_id}", None, headers)

    def list_workout_plans(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/workout-plans", params, headers)

    def set_workout_plan_status(
        self, plan_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/workout-plans/{plan_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # WorkoutAlternative
    # ------------------------------------------------------------------
    def create_workout_alternative(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/workout-alternatives", payload, headers)

    def get_workout_alternative(
        self, alternative_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/workout-alternatives/{alternative_id}", None, headers
        )

    def list_workout_alternatives(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/workout-alternatives", params, headers)

    # ------------------------------------------------------------------
    # ConsultationRequest
    # ------------------------------------------------------------------
    def create_consultation(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/consultations", payload, headers)

    def get_consultation(
        self, consultation_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/consultations/{consultation_id}", None, headers
        )

    def list_consultations(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/consultations", params, headers)

    def respond_to_consultation(
        self, consultation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/consultations/{consultation_id}/response", payload, headers
        )

    def sweep_consultations(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/consultations/sweep", payload, headers)

    # ------------------------------------------------------------------
    # REOAsset
    # ------------------------------------------------------------------
    def create_reo_asset(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE}/reo-assets", payload, headers)

    def get_reo_asset(self, reo_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE}/reo-assets/{reo_id}", None, headers)

    def list_reo_assets(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/reo-assets", params, headers)

    def set_reo_asset_status(
        self, reo_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/reo-assets/{reo_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # FeeAccrual
    # ------------------------------------------------------------------
    def create_fee_accrual(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", f"{BASE}/fee-accruals", payload, headers)

    def get_fee_accrual(self, fee_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{BASE}/fee-accruals/{fee_id}", None, headers)

    def list_fee_accruals(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/fee-accruals", params, headers)

    def set_fee_accrual_status(
        self, fee_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/fee-accruals/{fee_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # DistributionReport
    # ------------------------------------------------------------------
    def create_distribution_report(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{BASE}/distribution-reports", payload, headers)

    def get_distribution_report(
        self, report_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{BASE}/distribution-reports/{report_id}", None, headers
        )

    def list_distribution_reports(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"{BASE}/distribution-reports", params, headers)

    def set_distribution_report_status(
        self, report_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{BASE}/distribution-reports/{report_id}/status", payload, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            f"{BASE}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for header-level probes
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Optional[Json] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._request(method, path, payload, headers)
