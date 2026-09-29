"""Typed client covering every endpoint of the pharmacy API.

One method per PRD endpoint. Every method takes the caller's headers explicitly so
that identity and role are always visible at the call site; list methods take an
optional ``params`` mapping for filters and pagination.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

__all__ = ["ApiClient", "api_client"]

Headers = Dict[str, str]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """HTTP client with one named method per endpoint."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__(base_url)
        # The harness reboots the server between tests, so a pooled keep-alive socket
        # can outlive the process that accepted it and the next request would surface a
        # spurious transport error instead of the API's answer. Asking for a fresh
        # connection per request removes that race without touching any semantics.
        self.session.headers["Connection"] = "close"

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(
        self, current_utc: str, headers: Optional[Headers] = None
    ) -> requests.Response:
        """Set the logical clock. Requires no authentication."""
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers if headers is not None else {"Content-Type": "application/json"},
        )

    def set_clock_raw(self, payload: Payload, headers: Headers) -> requests.Response:
        """Set the logical clock with an arbitrary body."""
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Insurance plans
    # ------------------------------------------------------------------
    def create_insurance_plan(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/insurance-plans", payload, headers)

    def get_insurance_plan(self, plan_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/insurance-plans/{plan_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/patients", payload, headers)

    def list_patients(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/patients", None, headers, params)

    def get_patient(self, patient_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/patients/{patient_id}", None, headers)

    def get_adherence_summary(self, patient_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/patients/{patient_id}/adherence-summary", None, headers
        )

    def synchronize_patient(
        self, patient_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/patients/{patient_id}/synchronize", payload, headers
        )

    def set_autoship(
        self, patient_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/patients/{patient_id}/autoship", payload, headers
        )

    def report_dose_events(
        self, patient_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/patients/{patient_id}/dose-events", payload, headers
        )

    def run_adherence_review(
        self, patient_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/patients/{patient_id}/adherence-review",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Prescriptions
    # ------------------------------------------------------------------
    def create_prescription(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/prescriptions", payload, headers)

    def list_prescriptions(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/prescriptions", None, headers, params)

    def get_prescription(self, prescription_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/prescriptions/{prescription_id}", None, headers
        )

    def regimen_change(
        self, prescription_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/prescriptions/{prescription_id}/regimen-change",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Fill cycles
    # ------------------------------------------------------------------
    def create_fill_cycle(self, payload: Payload, headers: Headers) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/fill-cycles", payload, headers)

    def list_fill_cycles(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fill-cycles", None, headers, params)

    def get_fill_cycle(self, cycle_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/fill-cycles/{cycle_id}", None, headers)

    def adjudicate_fill_cycle(
        self, cycle_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/fill-cycles/{cycle_id}/adjudicate",
            payload if payload is not None else {},
            headers,
        )

    def generate_roll(
        self, cycle_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/fill-cycles/{cycle_id}/generate-roll",
            payload if payload is not None else {},
            headers,
        )

    def reissue_fill_cycle(
        self, cycle_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fill-cycles/{cycle_id}/reissue", payload, headers
        )

    def list_cycle_adherence_events(
        self, cycle_id: str, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/fill-cycles/{cycle_id}/adherence-events",
            None,
            headers,
            params,
        )

    # ------------------------------------------------------------------
    # Cycle lines
    # ------------------------------------------------------------------
    def list_cycle_lines(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cycle-lines", None, headers, params)

    def get_cycle_line(self, line_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cycle-lines/{line_id}", None, headers)

    # ------------------------------------------------------------------
    # Pouch rolls
    # ------------------------------------------------------------------
    def list_pouch_rolls(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/pouch-rolls", None, headers, params)

    def get_pouch_roll(self, roll_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/pouch-rolls/{roll_id}", None, headers)

    def pack_roll(
        self, roll_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/pouch-rolls/{roll_id}/pack",
            payload if payload is not None else {},
            headers,
        )

    def capture_roll_images(
        self, roll_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/pouch-rolls/{roll_id}/verification-images",
            payload,
            headers,
        )

    def verify_roll(
        self, roll_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/pouch-rolls/{roll_id}/verify",
            payload if payload is not None else {},
            headers,
        )

    def rework_roll(
        self, roll_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/pouch-rolls/{roll_id}/rework",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Pouches
    # ------------------------------------------------------------------
    def list_pouches(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/pouches", None, headers, params)

    def get_pouch(self, pouch_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/pouches/{pouch_id}", None, headers)

    def capture_pouch_image(
        self, pouch_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/pouches/{pouch_id}/verification-image", payload, headers
        )

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    def stage_shipment(
        self, cycle_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/fill-cycles/{cycle_id}/shipments", payload, headers
        )

    def list_shipments(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shipments", None, headers, params)

    def get_shipment(self, shipment_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/shipments/{shipment_id}", None, headers)

    def dispatch_shipment(
        self, shipment_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/dispatch",
            payload if payload is not None else {},
            headers,
        )

    def deliver_shipment(
        self, shipment_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/deliver",
            payload if payload is not None else {},
            headers,
        )

    def confirm_pickup(
        self, shipment_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/shipments/{shipment_id}/confirm-pickup",
            payload if payload is not None else {},
            headers,
        )

    # ------------------------------------------------------------------
    # Refill authorizations
    # ------------------------------------------------------------------
    def create_refill_authorization(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/refill-authorizations", payload, headers
        )

    def list_refill_authorizations(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/refill-authorizations", None, headers, params
        )

    def get_refill_authorization(self, auth_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/refill-authorizations/{auth_id}", None, headers
        )

    def chase_refill_authorization(
        self, auth_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/refill-authorizations/{auth_id}/chase",
            payload if payload is not None else {},
            headers,
        )

    def escalate_refill_authorization(
        self, auth_id: str, headers: Headers, payload: Payload = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/refill-authorizations/{auth_id}/escalate",
            payload if payload is not None else {},
            headers,
        )

    def respond_refill_authorization(
        self, auth_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/refill-authorizations/{auth_id}/respond",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Travel (vacation) exceptions
    # ------------------------------------------------------------------
    def create_vacation_exception(
        self, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/vacation-exceptions", payload, headers)

    def list_vacation_exceptions(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vacation-exceptions", None, headers, params
        )

    def get_vacation_exception(
        self, exception_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vacation-exceptions/{exception_id}", None, headers
        )

    def decide_vacation_exception(
        self, exception_id: str, payload: Payload, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/vacation-exceptions/{exception_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Credit memos
    # ------------------------------------------------------------------
    def list_credit_memos(self, headers: Headers, params: Params = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/credit-memos", None, headers, params)

    def get_credit_memo(self, memo_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/credit-memos/{memo_id}", None, headers)

    # ------------------------------------------------------------------
    # Adherence events
    # ------------------------------------------------------------------
    def list_adherence_events(
        self, headers: Headers, params: Params = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/adherence-events", None, headers, params)

    def get_adherence_event(self, event_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/adherence-events/{event_id}", None, headers
        )


api_client = ApiClient()
