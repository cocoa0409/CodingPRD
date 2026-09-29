"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under the `/rehab` prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

API_PREFIX = "/rehab"


class ApiClient(GenericApiClient):
    """Endpoint methods for the Homeowner Rehabilitation Loan Program API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, now: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", {"now": now}, headers
        )

    # ------------------------------------------------------------------
    # Program years
    # ------------------------------------------------------------------

    def create_program_year(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/program-years", payload, headers)

    def get_program_year(self, program_year_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/program-years/{program_year_id}", headers=headers
        )

    def list_program_years(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/program-years", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Applicants (households)
    # ------------------------------------------------------------------

    def create_applicant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/applicants", payload, headers)

    def update_applicant(
        self, applicant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH", f"{API_PREFIX}/applicants/{applicant_id}", payload, headers
        )

    def verify_income(self, applicant_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/applicants/{applicant_id}/verify-income", {}, headers
        )

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/applicants/{applicant_id}", headers=headers
        )

    def list_applicants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/applicants", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Rehabilitation applications
    # ------------------------------------------------------------------

    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/applications", payload, headers)

    def verify_ownership(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/applications/{application_id}/verify-ownership",
            payload,
            headers,
        )

    def record_lead_clearance(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/applications/{application_id}/lead-clearance",
            payload,
            headers,
        )

    def record_historic_clearance(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/applications/{application_id}/historic-clearance",
            payload,
            headers,
        )

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/applications", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Property inspections
    # ------------------------------------------------------------------

    def create_inspection(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/inspections", payload, headers)

    def record_inspection_result(
        self, inspection_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/inspections/{inspection_id}/record-result",
            payload,
            headers,
        )

    def get_inspection(self, inspection_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/inspections/{inspection_id}", headers=headers
        )

    def list_inspections(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/inspections", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Work write-ups
    # ------------------------------------------------------------------

    def create_write_up(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/write-ups", payload, headers)

    def submit_write_up(self, write_up_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/write-ups/{write_up_id}/submit", {}, headers
        )

    def request_write_up_revision(
        self, write_up_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/write-ups/{write_up_id}/request-revision",
            payload,
            headers,
        )

    def approve_write_up(self, write_up_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/write-ups/{write_up_id}/approve", {}, headers
        )

    def get_write_up(self, write_up_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/write-ups/{write_up_id}", headers=headers
        )

    def list_write_ups(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/write-ups", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Repair lines
    # ------------------------------------------------------------------

    def create_work_item(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/work-items", payload, headers)

    def delete_work_item(self, work_item_id: str, headers: Dict[str, str]):
        return self._request(
            "DELETE", f"{API_PREFIX}/work-items/{work_item_id}", headers=headers
        )

    def get_work_item(self, work_item_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/work-items/{work_item_id}", headers=headers
        )

    def list_work_items(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/work-items", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Contractors
    # ------------------------------------------------------------------

    def create_contractor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/contractors", payload, headers)

    def set_contractor_status(
        self, contractor_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/contractors/{contractor_id}/status", payload, headers
        )

    def get_contractor(self, contractor_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/contractors/{contractor_id}", headers=headers
        )

    def list_contractors(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/contractors", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Bid solicitations
    # ------------------------------------------------------------------

    def create_bid_solicitation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/bid-solicitations", payload, headers
        )

    def tabulate_solicitation(self, solicitation_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/bid-solicitations/{solicitation_id}/tabulate",
            {},
            headers,
        )

    def award_solicitation(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/bid-solicitations/{solicitation_id}/award",
            payload,
            headers,
        )

    def reopen_solicitation(
        self, solicitation_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/bid-solicitations/{solicitation_id}/reopen",
            payload,
            headers,
        )

    def get_solicitation(self, solicitation_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"{API_PREFIX}/bid-solicitations/{solicitation_id}",
            headers=headers,
        )

    def list_solicitations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/bid-solicitations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Bids
    # ------------------------------------------------------------------

    def create_bid(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/bids", payload, headers)

    def get_bid(self, bid_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/bids/{bid_id}", headers=headers)

    def list_bids(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/bids", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Loans
    # ------------------------------------------------------------------

    def create_loan(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/loans", payload, headers)

    def record_lien(
        self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/record-lien", payload, headers
        )

    def close_out_loan(
        self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/close-out", payload, headers
        )

    def post_loan_payment(
        self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/payments", payload, headers
        )

    def record_recapture(
        self, loan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{API_PREFIX}/loans/{loan_id}/recapture", payload, headers
        )

    def get_loan(self, loan_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{API_PREFIX}/loans/{loan_id}", headers=headers)

    def list_loans(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/loans", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Draw requests
    # ------------------------------------------------------------------

    def create_draw_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/draw-requests", payload, headers)

    def approve_draw_request(self, draw_request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/draw-requests/{draw_request_id}/approve",
            {},
            headers,
        )

    def pay_draw_request(self, draw_request_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/draw-requests/{draw_request_id}/pay", {}, headers
        )

    def get_draw_request(self, draw_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/draw-requests/{draw_request_id}", headers=headers
        )

    def list_draw_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/draw-requests", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Change orders
    # ------------------------------------------------------------------

    def create_change_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/change-orders", payload, headers)

    def approve_change_order(self, change_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{API_PREFIX}/change-orders/{change_order_id}/approve",
            {},
            headers,
        )

    def deny_change_order(
        self, change_order_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/change-orders/{change_order_id}/deny",
            payload,
            headers,
        )

    def get_change_order(self, change_order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/change-orders/{change_order_id}", headers=headers
        )

    def list_change_orders(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{API_PREFIX}/change-orders", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Complaint cases
    # ------------------------------------------------------------------

    def create_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{API_PREFIX}/complaints", payload, headers)

    def notify_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{API_PREFIX}/complaints/{complaint_id}/notify", {}, headers
        )

    def resolve_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/complaints/{complaint_id}/resolve",
            payload,
            headers,
        )

    def sanction_complaint(
        self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{API_PREFIX}/complaints/{complaint_id}/sanction",
            payload,
            headers,
        )

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{API_PREFIX}/complaints/{complaint_id}", headers=headers
        )

    def list_complaints(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET", f"{API_PREFIX}/complaints", headers=headers, params=params
        )


api_client = ApiClient()
