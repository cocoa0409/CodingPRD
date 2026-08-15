"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Fleet: vessels, season rates, geo zones, maintenance, advisories
    # ------------------------------------------------------------------
    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def create_season_rate(self, payload, headers):
        return self._request("POST", "/season-rates", payload, headers)

    def create_geo_zone(self, payload, headers):
        return self._request("POST", "/geo-zones", payload, headers)

    def create_maintenance_window(self, vessel_id, payload, headers):
        return self._request("POST", f"/vessels/{vessel_id}/maintenance-windows",
                             payload, headers)

    def list_maintenance_windows(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}/maintenance-windows",
                             headers=headers)

    def create_weather_advisory(self, payload, headers):
        return self._request("POST", "/weather-advisories", payload, headers)

    # ------------------------------------------------------------------
    # Renters and safety certificates
    # ------------------------------------------------------------------
    def create_renter(self, payload, headers):
        return self._request("POST", "/renters", payload, headers)

    def get_renter(self, renter_id, headers):
        return self._request("GET", f"/renters/{renter_id}", headers=headers)

    def submit_certificate(self, renter_id, payload, headers):
        return self._request("POST", f"/renters/{renter_id}/certificates",
                             payload, headers)

    def list_certificates(self, renter_id, headers):
        return self._request("GET", f"/renters/{renter_id}/certificates",
                             headers=headers)

    def decide_certificate(self, certificate_id, payload, headers):
        return self._request("POST", f"/certificates/{certificate_id}/decision",
                             payload, headers)

    # ------------------------------------------------------------------
    # Bookings and their sub-resources
    # ------------------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", {}, headers)

    def modify_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/modify", payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    def put_itinerary(self, booking_id, payload, headers):
        return self._request("PUT", f"/bookings/{booking_id}/itinerary", payload, headers)

    def list_itineraries(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/itinerary", headers=headers)

    def sign_orientation_item(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/orientation/sign-item",
                             payload, headers)

    def countersign_orientation(self, booking_id, payload, headers):
        return self._request("POST",
                             f"/bookings/{booking_id}/orientation/countersign",
                             payload, headers)

    def checkout_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/checkout", payload, headers)

    def return_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/return", payload, headers)

    def settle_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/settle", {}, headers)

    def list_cleaning_turns(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/cleaning-turns",
                             headers=headers)

    def inspect_cleaning_turn(self, turn_id, payload, headers):
        return self._request("POST", f"/cleaning-turns/{turn_id}/inspect",
                             payload, headers)

    def report_incident(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/incidents",
                             payload, headers)

    def list_incidents(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/incidents", headers=headers)

    def resolve_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/incidents/{incident_id}/resolve",
                             payload, headers)

    def list_charges(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/charges", headers=headers)


api_client = ApiClient()
