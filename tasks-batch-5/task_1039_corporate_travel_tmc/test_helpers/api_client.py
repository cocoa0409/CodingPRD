"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock / maintenance ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_sweep(self, headers):
        return self._request("POST", "/tmc/maintenance/run-sweep", {}, headers)

    # ---- TravelPolicy ----
    def create_travel_policy(self, payload, headers):
        return self._request("POST", "/tmc/travel-policies", payload, headers)

    def get_travel_policy(self, policy_id, headers):
        return self._request("GET", f"/tmc/travel-policies/{policy_id}", headers=headers)

    # ---- Traveler ----
    def create_traveler(self, payload, headers):
        return self._request("POST", "/tmc/travelers", payload, headers)

    def get_traveler(self, traveler_id, headers):
        return self._request("GET", f"/tmc/travelers/{traveler_id}", headers=headers)

    def list_travelers(self, headers, params=None):
        return self._request("GET", "/tmc/travelers", headers=headers, params=params)

    def suspend_traveler(self, traveler_id, headers):
        return self._request("POST", f"/tmc/travelers/{traveler_id}/suspend", {}, headers)

    def reactivate_traveler(self, traveler_id, headers):
        return self._request("POST", f"/tmc/travelers/{traveler_id}/reactivate", {}, headers)

    # ---- Vendor ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/tmc/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/tmc/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/tmc/vendors", headers=headers, params=params)

    def deactivate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/tmc/vendors/{vendor_id}/deactivate", {}, headers)

    def get_savings_report(self, vendor_id, headers):
        return self._request("GET", f"/tmc/vendors/{vendor_id}/savings-report", headers=headers)

    # ---- NegotiatedRate ----
    def create_negotiated_rate(self, payload, headers):
        return self._request("POST", "/tmc/negotiated-rates", payload, headers)

    def get_negotiated_rate(self, rate_id, headers):
        return self._request("GET", f"/tmc/negotiated-rates/{rate_id}", headers=headers)

    def list_negotiated_rates(self, headers, params=None):
        return self._request("GET", "/tmc/negotiated-rates", headers=headers, params=params)

    # ---- TripRequest ----
    def create_trip_request(self, payload, headers):
        return self._request("POST", "/tmc/trip-requests", payload, headers)

    def get_trip_request(self, trip_id, headers):
        return self._request("GET", f"/tmc/trip-requests/{trip_id}", headers=headers)

    def list_trip_requests(self, headers, params=None):
        return self._request("GET", "/tmc/trip-requests", headers=headers, params=params)

    def submit_trip_request(self, trip_id, headers):
        return self._request("POST", f"/tmc/trip-requests/{trip_id}/submit", {}, headers)

    def approve_trip_request(self, trip_id, headers):
        return self._request("POST", f"/tmc/trip-requests/{trip_id}/approve", {}, headers)

    def reject_trip_request(self, trip_id, headers, payload=None):
        return self._request("POST", f"/tmc/trip-requests/{trip_id}/reject", payload or {}, headers)

    def cancel_trip_request(self, trip_id, headers):
        return self._request("POST", f"/tmc/trip-requests/{trip_id}/cancel", {}, headers)

    # ---- Booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/tmc/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/tmc/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/tmc/bookings", headers=headers, params=params)

    def exchange_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/tmc/bookings/{booking_id}/exchange", payload, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/tmc/bookings/{booking_id}/cancel", {}, headers)

    # ---- GroupBooking ----
    def create_group_booking(self, payload, headers):
        return self._request("POST", "/tmc/group-bookings", payload, headers)

    def get_group_booking(self, gb_id, headers):
        return self._request("GET", f"/tmc/group-bookings/{gb_id}", headers=headers)

    def list_group_bookings(self, headers, params=None):
        return self._request("GET", "/tmc/group-bookings", headers=headers, params=params)

    def confirm_group_booking(self, gb_id, payload, headers):
        return self._request("POST", f"/tmc/group-bookings/{gb_id}/confirm", payload, headers)

    def release_group_booking(self, gb_id, headers):
        return self._request("POST", f"/tmc/group-bookings/{gb_id}/release", {}, headers)

    def cancel_group_booking(self, gb_id, headers):
        return self._request("POST", f"/tmc/group-bookings/{gb_id}/cancel", {}, headers)

    # ---- UnusedTicketCredit ----
    def get_unused_ticket_credit(self, credit_id, headers):
        return self._request("GET", f"/tmc/unused-ticket-credits/{credit_id}", headers=headers)

    def list_unused_ticket_credits(self, headers, params=None):
        return self._request("GET", "/tmc/unused-ticket-credits", headers=headers, params=params)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/tmc/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/tmc/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/tmc/invoices", headers=headers, params=params)

    def reconcile_invoice(self, invoice_id, headers):
        return self._request("POST", f"/tmc/invoices/{invoice_id}/reconcile", {}, headers)

    def resolve_dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/tmc/invoices/{invoice_id}/resolve-dispute", payload, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/tmc/invoices/{invoice_id}/pay", {}, headers)

    # ---- InvoiceLine ----
    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/tmc/invoice-lines/{line_id}", headers=headers)

    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", "/tmc/invoice-lines", headers=headers, params=params)


api_client = ApiClient()
