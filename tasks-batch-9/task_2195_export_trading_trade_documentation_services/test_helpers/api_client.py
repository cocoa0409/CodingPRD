"""Typed client with one method per declared endpoint."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

Headers = Dict[str, str]
Json = Dict[str, Any]


class ApiClient(GenericApiClient):
    """One method per endpoint. Every method returns the raw response."""

    # ------------------------------------------------------------------
    # logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Headers) -> requests.Response:
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            payload={"current_utc": current_utc},
            headers=headers,
        )

    def set_clock_raw(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", payload=payload, headers=headers
        )

    # ------------------------------------------------------------------
    # foreign buyers
    # ------------------------------------------------------------------
    def create_buyer(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/foreign-buyers", payload=payload, headers=headers)

    def get_buyer(self, buyer_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/foreign-buyers/{buyer_id}", headers=headers)

    def patch_restricted_party_flag(
        self, buyer_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "PATCH",
            f"/foreign-buyers/{buyer_id}/restricted-party-flag",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # export orders
    # ------------------------------------------------------------------
    def create_order(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/export-orders", payload=payload, headers=headers)

    def list_orders(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/export-orders", payload=params, headers=headers)

    def get_order(self, order_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/export-orders/{order_id}", headers=headers)

    def get_cost_allocation(
        self, order_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/export-orders/{order_id}/cost-allocation", headers=headers
        )

    def add_shipment_line(
        self, order_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/export-orders/{order_id}/shipment-lines",
            payload=payload,
            headers=headers,
        )

    def list_order_shipment_lines(
        self, order_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/export-orders/{order_id}/shipment-lines",
            payload=params,
            headers=headers,
        )

    def submit_for_compliance(
        self, order_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/export-orders/{order_id}/submit-for-compliance",
            payload=payload or {},
            headers=headers,
        )

    def cancel_order(
        self, order_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/export-orders/{order_id}/cancel", payload=payload, headers=headers
        )

    def write_off_order(
        self, order_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/export-orders/{order_id}/write-off",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # shipment lines (flat reads)
    # ------------------------------------------------------------------
    def list_shipment_lines(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/shipment-lines", payload=params, headers=headers)

    def get_shipment_line(self, line_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/shipment-lines/{line_id}", headers=headers)

    # ------------------------------------------------------------------
    # export control screenings and licenses
    # ------------------------------------------------------------------
    def list_screenings(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/export-control-screenings", payload=params, headers=headers
        )

    def get_screening(self, screening_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/export-control-screenings/{screening_id}", headers=headers
        )

    def record_screening_decision(
        self, screening_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/export-control-screenings/{screening_id}/decision",
            payload=payload,
            headers=headers,
        )

    def create_license(
        self, screening_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/export-control-screenings/{screening_id}/licenses",
            payload=payload,
            headers=headers,
        )

    def clear_with_license(
        self, screening_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/export-control-screenings/{screening_id}/clear-with-license",
            payload=payload,
            headers=headers,
        )

    def list_licenses(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/export-licenses", payload=params, headers=headers)

    def get_license(self, license_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/export-licenses/{license_id}", headers=headers)

    # ------------------------------------------------------------------
    # letters of credit
    # ------------------------------------------------------------------
    def capture_credit(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/letters-of-credit", payload=payload, headers=headers
        )

    def list_credits(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/letters-of-credit", payload=params, headers=headers
        )

    def get_credit(self, lc_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/letters-of-credit/{lc_id}", headers=headers)

    def open_terms_review(
        self, lc_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/letters-of-credit/{lc_id}/reviews",
            payload=payload,
            headers=headers,
        )

    def amend_credit(
        self, lc_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/letters-of-credit/{lc_id}/amendments",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # terms reviews and findings
    # ------------------------------------------------------------------
    def list_terms_reviews(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/lc-terms-reviews", payload=params, headers=headers
        )

    def get_terms_review(self, review_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/lc-terms-reviews/{review_id}", headers=headers)

    def raise_terms_finding(
        self, review_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/lc-terms-reviews/{review_id}/findings",
            payload=payload,
            headers=headers,
        )

    def submit_terms_review(
        self, review_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/lc-terms-reviews/{review_id}/submit",
            payload=payload,
            headers=headers,
        )

    def list_findings(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/discrepancy-findings", payload=params, headers=headers
        )

    def get_finding(self, finding_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/discrepancy-findings/{finding_id}", headers=headers
        )

    def waive_finding(
        self, finding_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/discrepancy-findings/{finding_id}/waiver",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # trade documents
    # ------------------------------------------------------------------
    def generate_document(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/trade-documents", payload=payload, headers=headers
        )

    def list_documents(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/trade-documents", payload=params, headers=headers)

    def get_document(self, document_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/trade-documents/{document_id}", headers=headers)

    def issue_document(
        self, document_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/trade-documents/{document_id}/issue",
            payload=payload or {},
            headers=headers,
        )

    def regenerate_document(
        self, document_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/trade-documents/{document_id}/regenerate",
            payload=payload,
            headers=headers,
        )

    def void_document(
        self, document_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/trade-documents/{document_id}/void",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # presentation document links
    # ------------------------------------------------------------------
    def list_presentation_links(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/presentation-document-links", payload=params, headers=headers
        )

    def get_presentation_link(self, link_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/presentation-document-links/{link_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # vessel sailings and freight bookings
    # ------------------------------------------------------------------
    def create_sailing(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/vessel-sailings", payload=payload, headers=headers
        )

    def get_sailing(self, sailing_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/vessel-sailings/{sailing_id}", headers=headers)

    def create_booking(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/freight-bookings", payload=payload, headers=headers
        )

    def list_bookings(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/freight-bookings", payload=params, headers=headers
        )

    def get_booking(self, booking_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/freight-bookings/{booking_id}", headers=headers)

    def confirm_booking(
        self, booking_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/freight-bookings/{booking_id}/confirm",
            payload=payload or {},
            headers=headers,
        )

    def cancel_booking(
        self, booking_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/freight-bookings/{booking_id}/cancel",
            payload=payload,
            headers=headers,
        )

    def issue_bill_of_lading(
        self, booking_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/freight-bookings/{booking_id}/bill-of-lading",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # document presentations
    # ------------------------------------------------------------------
    def lodge_presentation(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/document-presentations", payload=payload, headers=headers
        )

    def list_presentations(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/document-presentations", payload=params, headers=headers
        )

    def get_presentation(
        self, presentation_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/document-presentations/{presentation_id}", headers=headers
        )

    def examine_presentation(
        self, presentation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/document-presentations/{presentation_id}/examine",
            payload=payload,
            headers=headers,
        )

    def cure_presentation(
        self, presentation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/document-presentations/{presentation_id}/cure",
            payload=payload,
            headers=headers,
        )

    def settle_presentation(
        self, presentation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/document-presentations/{presentation_id}/settlement",
            payload=payload,
            headers=headers,
        )

    def dishonour_presentation(
        self, presentation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/document-presentations/{presentation_id}/dishonour",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # credit insurance policies
    # ------------------------------------------------------------------
    def create_policy(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request(
            "POST", "/credit-insurance-policies", payload=payload, headers=headers
        )

    def list_policies(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", "/credit-insurance-policies", payload=params, headers=headers
        )

    def get_policy(self, policy_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/credit-insurance-policies/{policy_id}", headers=headers
        )

    def file_claim(
        self, policy_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/credit-insurance-policies/{policy_id}/claims",
            payload=payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # dispute cases
    # ------------------------------------------------------------------
    def open_dispute(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/dispute-cases", payload=payload, headers=headers)

    def list_disputes(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/dispute-cases", payload=params, headers=headers)

    def get_dispute(self, dispute_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/dispute-cases/{dispute_id}", headers=headers)

    def make_offer(
        self, dispute_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/dispute-cases/{dispute_id}/offers", payload=payload, headers=headers
        )

    def counter_offer(
        self, dispute_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/dispute-cases/{dispute_id}/counter",
            payload=payload,
            headers=headers,
        )

    def accept_dispute(
        self, dispute_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/dispute-cases/{dispute_id}/accept",
            payload=payload or {},
            headers=headers,
        )

    def close_dispute(
        self, dispute_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/dispute-cases/{dispute_id}/close", payload=payload, headers=headers
        )


api_client = ApiClient()
