"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ──────────── Venues / inventory configuration ────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def archive_venue(self, venue_id, headers):
        return self._request("POST", f"/venues/{venue_id}/archive", headers=headers)

    def create_space(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/spaces", payload, headers)

    def list_spaces(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/spaces", headers=headers, params=params)

    def create_package(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/packages", payload, headers)

    def list_packages(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/packages", headers=headers, params=params)

    def create_coordinator(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/coordinators", payload, headers)

    def list_coordinators(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/coordinators", headers=headers, params=params)

    def get_coordinator(self, coordinator_id, headers):
        return self._request("GET", f"/coordinators/{coordinator_id}", headers=headers)

    # ──────────── Clients ────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ──────────── Bookings ────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def assign_coordinator(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/assign-coordinator", payload, headers)

    def create_hold(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/holds", payload, headers)

    def list_holds_for_booking(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/holds", headers=headers, params=params)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/holds", headers=headers, params=params)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/holds/{hold_id}", headers=headers)

    def delete_hold(self, booking_id, hold_id, headers):
        return self._request("DELETE", f"/bookings/{booking_id}/holds/{hold_id}", headers=headers)

    def place_hold(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/place-hold", {}, headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def guarantee_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/guarantee", payload, headers)

    def get_guarantee(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/guarantee", headers=headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    # ──────────── Payments & milestones ────────────
    def list_milestones(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/milestones", headers=headers, params=params)

    def post_payment(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/payments", payload, headers)

    def list_payments(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/payments", headers=headers, params=params)

    # ──────────── Vendors & COI ────────────
    def create_vendor(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/vendors", payload, headers)

    def list_vendors(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/vendors", headers=headers, params=params)

    def upload_coi(self, vendor_id, payload, headers):
        return self._request("POST", f"/vendors/{vendor_id}/coi", payload, headers)

    def reject_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reject", {}, headers)

    # ──────────── Walkthroughs ────────────
    def create_walkthrough(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/walkthroughs", payload, headers)

    def list_walkthroughs(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/walkthroughs", headers=headers, params=params)

    # ──────────── Reschedule / force-majeure ────────────
    def create_reschedule_request(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule-requests", payload, headers)

    def list_reschedule_requests_for_booking(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/reschedule-requests", headers=headers, params=params)

    def list_reschedule_requests(self, headers, params=None):
        return self._request("GET", "/reschedule-requests", headers=headers, params=params)

    def get_reschedule_request(self, request_id, headers):
        return self._request("GET", f"/reschedule-requests/{request_id}", headers=headers)

    def counter_reschedule(self, request_id, payload, headers):
        return self._request("POST", f"/reschedule-requests/{request_id}/counter", payload, headers)

    def approve_reschedule(self, request_id, payload, headers):
        return self._request("POST", f"/reschedule-requests/{request_id}/approve", payload, headers)

    def decline_reschedule(self, request_id, headers):
        return self._request("POST", f"/reschedule-requests/{request_id}/decline", {}, headers)

    def withdraw_reschedule(self, request_id, headers):
        return self._request("POST", f"/reschedule-requests/{request_id}/withdraw", {}, headers)

    # ──────────── Test-driving clock ────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def expire_hold(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/expire-hold", {}, headers)


api_client = ApiClient()
