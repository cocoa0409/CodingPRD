"""API client: one method per endpoint defined in the Intercity Ticketing PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Clock (test-driving) ──
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ── Operator ──
    def create_operator(self, payload, headers):
        return self._request("POST", "/v1/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/v1/operators/{operator_id}", headers=headers)

    # ── FareClass ──
    def create_fare_class(self, payload, headers):
        return self._request("POST", "/v1/fare-classes", payload, headers)

    def list_fare_classes(self, headers, params=None):
        return self._request("GET", "/v1/fare-classes", headers=headers, params=params)

    def get_fare_class(self, fare_class_id, headers):
        return self._request("GET", f"/v1/fare-classes/{fare_class_id}", headers=headers)

    def retire_fare_class(self, fare_class_id, headers):
        return self._request(
            "POST", f"/v1/fare-classes/{fare_class_id}/retire", {}, headers
        )

    # ── Route ──
    def create_route(self, payload, headers):
        return self._request("POST", "/v1/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/v1/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/v1/routes/{route_id}", headers=headers)

    def publish_route(self, route_id, headers):
        return self._request("POST", f"/v1/routes/{route_id}/publish", {}, headers)

    # ── ServiceDate ──
    def create_service_date(self, payload, headers):
        return self._request("POST", "/v1/service-dates", payload, headers)

    def list_service_dates(self, headers, params=None):
        return self._request("GET", "/v1/service-dates", headers=headers, params=params)

    def get_service_date(self, service_date_id, headers):
        return self._request("GET", f"/v1/service-dates/{service_date_id}", headers=headers)

    def delay_service_date(self, service_date_id, headers):
        return self._request(
            "POST", f"/v1/service-dates/{service_date_id}/delay", {}, headers
        )

    def restore_service_date(self, service_date_id, headers):
        return self._request(
            "POST", f"/v1/service-dates/{service_date_id}/restore", {}, headers
        )

    def depart_service_date(self, service_date_id, headers):
        return self._request(
            "POST", f"/v1/service-dates/{service_date_id}/depart", {}, headers
        )

    def cancel_service_date(self, service_date_id, headers):
        return self._request(
            "POST", f"/v1/service-dates/{service_date_id}/cancel", {}, headers
        )

    def suspend_sales(self, service_date_id, headers):
        return self._request(
            "POST", f"/v1/service-dates/{service_date_id}/suspend-sales", {}, headers
        )

    def resume_sales(self, service_date_id, headers):
        return self._request(
            "POST", f"/v1/service-dates/{service_date_id}/resume-sales", {}, headers
        )

    # ── Passenger ──
    def create_passenger(self, payload, headers):
        return self._request("POST", "/v1/passengers", payload, headers)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"/v1/passengers/{passenger_id}", headers=headers)

    # ── TravelPass ──
    def create_pass(self, payload, headers):
        return self._request("POST", "/v1/passes", payload, headers)

    def list_passes(self, headers, params=None):
        return self._request("GET", "/v1/passes", headers=headers, params=params)

    def get_pass(self, pass_id, headers):
        return self._request("GET", f"/v1/passes/{pass_id}", headers=headers)

    # ── Booking ──
    def create_booking(self, payload, headers):
        return self._request("POST", "/v1/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/v1/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/v1/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/v1/bookings/{booking_id}/confirm", payload, headers
        )

    def pay_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/bookings/{booking_id}/pay", {}, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/v1/bookings/{booking_id}/cancel", payload, headers
        )

    def exchange_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/v1/bookings/{booking_id}/exchange", payload, headers
        )

    # ── BookingLeg ──
    def list_legs(self, headers, params=None):
        return self._request("GET", "/v1/legs", headers=headers, params=params)

    def get_leg(self, booking_leg_id, headers):
        return self._request("GET", f"/v1/legs/{booking_leg_id}", headers=headers)

    # ── Ticket ──
    def list_tickets(self, headers, params=None):
        return self._request("GET", "/v1/tickets", headers=headers, params=params)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/v1/tickets/{ticket_id}", headers=headers)

    def scan_ticket(self, ticket_id, headers):
        return self._request("POST", f"/v1/tickets/{ticket_id}/scan", {}, headers)

    # ── Baggage ──
    def add_baggage(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/v1/bookings/{booking_id}/baggage", payload, headers
        )

    def list_baggage(self, headers, params=None):
        return self._request("GET", "/v1/baggage", headers=headers, params=params)

    def get_baggage(self, baggage_item_id, headers):
        return self._request("GET", f"/v1/baggage/{baggage_item_id}", headers=headers)

    # ── Accessibility ──
    def create_accessibility_request(self, booking_leg_id, payload, headers):
        return self._request(
            "POST", f"/v1/legs/{booking_leg_id}/accessibility-requests", payload, headers
        )

    def list_accessibility_requests(self, headers, params=None):
        return self._request(
            "GET", "/v1/accessibility-requests", headers=headers, params=params
        )

    def get_accessibility_request(self, accessibility_request_id, headers):
        return self._request(
            "GET", f"/v1/accessibility-requests/{accessibility_request_id}", headers=headers
        )

    def grant_accessibility_request(self, accessibility_request_id, headers):
        return self._request(
            "POST",
            f"/v1/accessibility-requests/{accessibility_request_id}/grant",
            {},
            headers,
        )

    def deny_accessibility_request(self, accessibility_request_id, headers):
        return self._request(
            "POST",
            f"/v1/accessibility-requests/{accessibility_request_id}/deny",
            {},
            headers,
        )

    # ── Settlement notes (RefundCreditNote) ──
    def list_settlement_notes(self, headers, params=None):
        return self._request(
            "GET", "/v1/settlement-notes", headers=headers, params=params
        )

    def get_settlement_note(self, settlement_note_id, headers):
        return self._request(
            "GET", f"/v1/settlement-notes/{settlement_note_id}", headers=headers
        )


api_client = ApiClient()
