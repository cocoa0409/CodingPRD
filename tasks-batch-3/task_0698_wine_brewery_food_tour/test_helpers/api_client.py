"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock & verification (test-driving) -----------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def verify_age(self, guest_id, headers):
        return self._request("POST", "/_verify/age", {"guest_id": guest_id}, headers)

    # ---- TourProduct -------------------------------------------------------
    def create_tour_product(self, payload, headers):
        return self._request("POST", "/tour-products", payload, headers)

    def list_tour_products(self, headers, params=None):
        return self._request("GET", "/tour-products", headers=headers, params=params)

    def get_tour_product(self, product_id, headers):
        return self._request("GET", f"/tour-products/{product_id}", headers=headers)

    def publish_tour_product(self, product_id, headers):
        return self._request("POST", f"/tour-products/{product_id}/publish", {}, headers)

    def retire_tour_product(self, product_id, headers):
        return self._request("POST", f"/tour-products/{product_id}/retire", {}, headers)

    # ---- AddOn -------------------------------------------------------------
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def list_add_ons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    # ---- Vehicle -----------------------------------------------------------
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def set_vehicle_status(self, vehicle_id, status, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/set-status",
                             {"status": status}, headers)

    # ---- PartnerVenue ------------------------------------------------------
    def create_partner_venue(self, payload, headers):
        return self._request("POST", "/partner-venues", payload, headers)

    def get_partner_venue(self, venue_id, headers):
        return self._request("GET", f"/partner-venues/{venue_id}", headers=headers)

    def set_partner_venue_status(self, venue_id, status, headers):
        return self._request("POST", f"/partner-venues/{venue_id}/set-status",
                             {"status": status}, headers)

    # ---- PickupPoint -------------------------------------------------------
    def create_pickup_point(self, payload, headers):
        return self._request("POST", "/pickup-points", payload, headers)

    def get_pickup_point(self, pickup_id, headers):
        return self._request("GET", f"/pickup-points/{pickup_id}", headers=headers)

    # ---- Guest -------------------------------------------------------------
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def sign_waiver(self, guest_id, headers):
        return self._request("POST", f"/guests/{guest_id}/sign-waiver", {}, headers)

    # ---- Departure ---------------------------------------------------------
    def create_departure(self, payload, headers):
        return self._request("POST", "/departures", payload, headers)

    def list_departures(self, headers, params=None):
        return self._request("GET", "/departures", headers=headers, params=params)

    def get_departure(self, departure_id, headers):
        return self._request("GET", f"/departures/{departure_id}", headers=headers)

    def confirm_departure(self, departure_id, headers):
        return self._request("POST", f"/departures/{departure_id}/confirm", {}, headers)

    def depart_departure(self, departure_id, headers):
        return self._request("POST", f"/departures/{departure_id}/depart", {}, headers)

    def complete_departure(self, departure_id, headers):
        return self._request("POST", f"/departures/{departure_id}/complete", {}, headers)

    def cancel_departure_weather(self, departure_id, cancel_reason, headers):
        return self._request("POST", f"/departures/{departure_id}/cancel-weather",
                             {"cancel_reason": cancel_reason}, headers)

    def cancel_departure_ops(self, departure_id, cancel_reason, headers):
        return self._request("POST", f"/departures/{departure_id}/cancel-ops",
                             {"cancel_reason": cancel_reason}, headers)

    # ---- Stop --------------------------------------------------------------
    def create_stop(self, payload, headers):
        return self._request("POST", "/stops", payload, headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/stops/{stop_id}", headers=headers)

    # ---- VenueConfirmation -------------------------------------------------
    def create_venue_confirmation(self, payload, headers):
        return self._request("POST", "/venue-confirmations", payload, headers)

    def list_venue_confirmations(self, headers, params=None):
        return self._request("GET", "/venue-confirmations", headers=headers, params=params)

    def get_venue_confirmation(self, vc_id, headers):
        return self._request("GET", f"/venue-confirmations/{vc_id}", headers=headers)

    def confirm_venue_confirmation(self, vc_id, headers):
        return self._request("POST", f"/venue-confirmations/{vc_id}/confirm", {}, headers)

    def request_changes_venue_confirmation(self, vc_id, decline_note, headers):
        return self._request("POST", f"/venue-confirmations/{vc_id}/request-changes",
                             {"decline_note": decline_note}, headers)

    def resubmit_venue_confirmation(self, vc_id, requested_headcount, headers):
        return self._request("POST", f"/venue-confirmations/{vc_id}/resubmit",
                             {"requested_headcount": requested_headcount}, headers)

    def decline_venue_confirmation(self, vc_id, headers, decline_note=None):
        payload = {} if decline_note is None else {"decline_note": decline_note}
        return self._request("POST", f"/venue-confirmations/{vc_id}/decline", payload, headers)

    # ---- Booking -----------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def reserve_booking(self, booking_id, expected_departure_version, headers):
        return self._request("POST", f"/bookings/{booking_id}/reserve",
                             {"expected_departure_version": expected_departure_version}, headers)

    def pay_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/pay", {}, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)


api_client = ApiClient()
