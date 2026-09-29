"""One method per endpoint of the Youth Tournament Housing API (PRD §4).

Every path in §4 is mounted under ``/housing`` except the logical clock, which
PRD §2.5 places outside that prefix: "Note that this endpoint sits outside the
`/housing` prefix."
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

Payload = Dict[str, Any]
Headers = Dict[str, str]
Params = Dict[str, Any]


class ApiClient(GenericApiClient):
    """Thin transport wrapper. Assertions live in the tests, not here."""

    # -- Logical clock (PRD §2.5) -------------------------------------------

    def set_clock(self, payload: Payload, headers: Headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- Tournaments -------------------------------------------------------

    def create_tournament(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/tournaments", payload, headers)

    def get_tournament(self, tournament_id: str, headers: Headers):
        return self._request(
            "GET", f"/housing/tournaments/{tournament_id}", None, headers
        )

    def close_booking(self, tournament_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self._request(
            "POST",
            f"/housing/tournaments/{tournament_id}/close-booking",
            payload if payload is not None else {},
            headers,
        )

    # -- Hotels and teams --------------------------------------------------

    def create_hotel(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/hotels", payload, headers)

    def create_team(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/teams", payload, headers)

    # -- Hotel contracts ---------------------------------------------------

    def create_hotel_contract(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/hotel-contracts", payload, headers)

    def negotiate_contract(self, contract_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/housing/hotel-contracts/{contract_id}/negotiation", payload, headers
        )

    def get_hotel_contract(self, contract_id: str, headers: Headers):
        return self._request(
            "GET", f"/housing/hotel-contracts/{contract_id}", None, headers
        )

    def list_hotel_contracts(self, headers: Headers, params: Optional[Params] = None):
        return self._request("GET", "/housing/hotel-contracts", None, headers, params)

    def list_contract_room_blocks(
        self, contract_id: str, headers: Headers, params: Optional[Params] = None
    ):
        return self._request(
            "GET",
            f"/housing/hotel-contracts/{contract_id}/room-blocks",
            None,
            headers,
            params,
        )

    # -- Room blocks -------------------------------------------------------

    def create_room_block(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/room-blocks", payload, headers)

    def release_room_block(self, block_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self._request(
            "POST",
            f"/housing/room-blocks/{block_id}/release",
            payload if payload is not None else {},
            headers,
        )

    # -- Team registrations ------------------------------------------------

    def create_team_registration(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/team-registrations", payload, headers)

    def get_team_registration(self, registration_id: str, headers: Headers):
        return self._request(
            "GET", f"/housing/team-registrations/{registration_id}", None, headers
        )

    def list_team_registrations(self, headers: Headers, params: Optional[Params] = None):
        return self._request(
            "GET", "/housing/team-registrations", None, headers, params
        )

    def list_registration_exception_requests(
        self, registration_id: str, headers: Headers, params: Optional[Params] = None
    ):
        return self._request(
            "GET",
            f"/housing/team-registrations/{registration_id}/exception-requests",
            None,
            headers,
            params,
        )

    # -- Bookings ----------------------------------------------------------

    def create_booking(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Headers):
        return self._request("GET", f"/housing/bookings/{booking_id}", None, headers)

    def list_bookings(self, headers: Headers, params: Optional[Params] = None):
        return self._request("GET", "/housing/bookings", None, headers, params)

    def submit_rooming_list(self, booking_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/housing/bookings/{booking_id}/rooming-list", payload, headers
        )

    def list_rooming_list(
        self, booking_id: str, headers: Headers, params: Optional[Params] = None
    ):
        return self._request(
            "GET", f"/housing/bookings/{booking_id}/rooming-list", None, headers, params
        )

    def confirm_booking(self, booking_id: str, headers: Headers, payload: Optional[Payload] = None):
        return self._request(
            "POST",
            f"/housing/bookings/{booking_id}/confirm",
            payload if payload is not None else {},
            headers,
        )

    def cancel_booking(self, booking_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/housing/bookings/{booking_id}/cancel", payload, headers
        )

    def create_actualization(self, booking_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/housing/bookings/{booking_id}/actualizations", payload, headers
        )

    def list_actualization_reports(
        self, booking_id: str, headers: Headers, params: Optional[Params] = None
    ):
        return self._request(
            "GET",
            f"/housing/bookings/{booking_id}/actualization-reports",
            None,
            headers,
            params,
        )

    # -- Exception requests ------------------------------------------------

    def create_exception_request(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/exception-requests", payload, headers)

    def get_exception_request(self, request_id: str, headers: Headers):
        return self._request(
            "GET", f"/housing/exception-requests/{request_id}", None, headers
        )

    def review_exception_request(
        self, request_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/housing/exception-requests/{request_id}/review", payload, headers
        )

    def team_action_exception_request(
        self, request_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST",
            f"/housing/exception-requests/{request_id}/team-action",
            payload,
            headers,
        )

    # -- Complaints --------------------------------------------------------

    def create_complaint(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers: Headers):
        return self._request("GET", f"/housing/complaints/{complaint_id}", None, headers)

    def list_complaints(self, headers: Headers, params: Optional[Params] = None):
        return self._request("GET", "/housing/complaints", None, headers, params)

    def triage_complaint(self, complaint_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/housing/complaints/{complaint_id}/triage", payload, headers
        )

    def adjudicate_complaint(
        self, complaint_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST", f"/housing/complaints/{complaint_id}/adjudicate", payload, headers
        )

    # -- Rebate invoices ---------------------------------------------------

    def create_rebate_invoice(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/rebate-invoices", payload, headers)

    def get_rebate_invoice(self, invoice_id: str, headers: Headers):
        return self._request(
            "GET", f"/housing/rebate-invoices/{invoice_id}", None, headers
        )

    def list_rebate_invoices(self, headers: Headers, params: Optional[Params] = None):
        return self._request("GET", "/housing/rebate-invoices", None, headers, params)

    def invoice_lifecycle(self, invoice_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/housing/rebate-invoices/{invoice_id}/lifecycle", payload, headers
        )

    def remit_invoice(self, invoice_id: str, payload: Payload, headers: Headers):
        return self._request(
            "POST", f"/housing/rebate-invoices/{invoice_id}/remit", payload, headers
        )

    # -- Revenue distributions ---------------------------------------------

    def create_revenue_distribution(self, payload: Payload, headers: Headers):
        return self._request("POST", "/housing/revenue-distributions", payload, headers)

    def get_revenue_distribution(self, distribution_id: str, headers: Headers):
        return self._request(
            "GET", f"/housing/revenue-distributions/{distribution_id}", None, headers
        )

    def list_revenue_distributions(
        self, headers: Headers, params: Optional[Params] = None
    ):
        return self._request(
            "GET", "/housing/revenue-distributions", None, headers, params
        )

    def advance_distribution(
        self, distribution_id: str, payload: Payload, headers: Headers
    ):
        return self._request(
            "POST",
            f"/housing/revenue-distributions/{distribution_id}/advance",
            payload,
            headers,
        )


api_client = ApiClient()
