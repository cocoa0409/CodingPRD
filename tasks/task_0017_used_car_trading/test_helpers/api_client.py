"""API client: one method per endpoint defined by the used-car trading PRD §4.

Every method returns the raw ``requests.Response``; tests call validators on the
response. Path layout follows PRD §4 verbatim — paths are root-level (no /api
prefix), e.g. ``/vehicles``, ``/listings/{id}/bids``.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client. Endpoints are grouped by entity, mirroring PRD §4 ordering."""

    # ──────────────── Sellers / Buyers ────────────────

    def create_seller(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/sellers", payload, headers)

    def create_buyer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/buyers", payload, headers)

    def get_buyer(self, buyer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    # ──────────────── Vehicles & Assessments ────────────────

    def create_vehicle(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def create_assessment(self, vehicle_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/assessments", payload, headers
        )

    def request_onsite(
        self,
        assessment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/assessments/{assessment_id}/request-onsite", payload or {}, headers
        )

    def finalize_assessment(
        self, assessment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/assessments/{assessment_id}/finalize", payload, headers
        )

    def get_assessment(self, assessment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    # ──────────────── Listings ────────────────

    def create_listing(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/listings", payload, headers)

    def submit_listing(
        self,
        listing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/listings/{listing_id}/submit", payload or {}, headers
        )

    def approve_listing(
        self,
        listing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/listings/{listing_id}/approve", payload or {}, headers
        )

    def reject_listing(
        self,
        listing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/listings/{listing_id}/reject", payload or {}, headers
        )

    def return_listing_for_revision(
        self,
        listing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/listings/{listing_id}/return-for-revision",
            payload or {},
            headers,
        )

    def delist_listing(
        self,
        listing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/listings/{listing_id}/delist", payload or {}, headers
        )

    def list_listings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def get_listing(self, listing_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    # ──────────────── Bids ────────────────

    def place_bid(
        self, listing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/listings/{listing_id}/bids", payload, headers)

    def close_auction(
        self,
        listing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/listings/{listing_id}/close-auction", payload or {}, headers
        )

    def cancel_bid(
        self,
        bid_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/bids/{bid_id}/cancel", payload or {}, headers
        )

    def list_bids(
        self,
        listing_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET", f"/listings/{listing_id}/bids", headers=headers, params=params
        )

    # ──────────────── Reservations ────────────────

    def create_reservation(
        self,
        listing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/listings/{listing_id}/reservations", payload or {}, headers
        )

    def cancel_reservation(
        self,
        reservation_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", payload or {}, headers
        )

    def list_reservations(
        self,
        listing_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/listings/{listing_id}/reservations",
            headers=headers,
            params=params,
        )

    # ──────────────── Purchase Orders ────────────────

    def create_purchase_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def cancel_purchase_order(
        self,
        po_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/purchase-orders/{po_id}/cancel", payload or {}, headers
        )

    # ──────────────── Loans ────────────────

    def apply_loan(
        self, po_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/purchase-orders/{po_id}/loans", payload, headers
        )

    def run_credit_check(
        self,
        loan_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/loans/{loan_id}/run-credit-check", payload or {}, headers
        )

    def cancel_loan(
        self,
        loan_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/loans/{loan_id}/cancel", payload or {}, headers
        )

    def get_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    # ──────────────── Transfers ────────────────

    def get_transfer(self, transfer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def upload_transfer_doc(
        self, transfer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"/transfers/{transfer_id}/documents", payload, headers
        )

    def book_appointment(
        self, transfer_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/transfers/{transfer_id}/book-appointment", payload, headers
        )

    def rollback_transfer(
        self,
        transfer_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/transfers/{transfer_id}/rollback", payload or {}, headers
        )

    # ──────────────── Warranties / Claims ────────────────

    def get_warranty(self, warranty_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def file_warranty_claim(
        self, warranty_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/warranties/{warranty_id}/claims", payload, headers
        )

    def approve_warranty_claim(
        self,
        claim_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/approve", payload or {}, headers
        )

    def reject_warranty_claim(
        self,
        claim_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/reject", payload or {}, headers
        )

    # ──────────────── Disputes ────────────────

    def create_dispute(
        self, po_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/purchase-orders/{po_id}/disputes", payload, headers
        )

    def start_review_dispute(
        self,
        dispute_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/disputes/{dispute_id}/start-review", payload or {}, headers
        )

    def request_more_evidence(
        self,
        dispute_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/request-more-evidence",
            payload or {},
            headers,
        )

    def request_third_party(
        self,
        dispute_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/request-third-party",
            payload or {},
            headers,
        )

    def submit_third_party_report(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/disputes/{dispute_id}/submit-third-party-report",
            payload,
            headers,
        )

    def propose_resolution(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/disputes/{dispute_id}/propose-resolution", payload, headers
        )

    def execute_dispute(
        self,
        dispute_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/disputes/{dispute_id}/execute", payload or {}, headers
        )

    # ──────────────── External events / Clock ────────────────

    def emit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/emit", payload, headers)

    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    # ──────────────── Audit ────────────────

    def list_audit_logs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)


api_client = ApiClient()
