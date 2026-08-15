"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Launch sites
    # ------------------------------------------------------------------
    def create_launch_site(self, payload, headers):
        return self._request("POST", "/v1/launch-sites", payload, headers)

    def get_launch_site(self, site_id, headers):
        return self._request("GET", f"/v1/launch-sites/{site_id}", headers=headers)

    def launch_site_event(self, site_id, payload, headers):
        return self._request("POST", f"/v1/launch-sites/{site_id}/events", payload, headers)

    # ------------------------------------------------------------------
    # Balloons
    # ------------------------------------------------------------------
    def create_balloon(self, payload, headers):
        return self._request("POST", "/v1/balloons", payload, headers)

    def get_balloon(self, balloon_id, headers):
        return self._request("GET", f"/v1/balloons/{balloon_id}", headers=headers)

    def balloon_event(self, balloon_id, payload, headers):
        return self._request("POST", f"/v1/balloons/{balloon_id}/events", payload, headers)

    # ------------------------------------------------------------------
    # Pilots
    # ------------------------------------------------------------------
    def create_pilot(self, payload, headers):
        return self._request("POST", "/v1/pilots", payload, headers)

    def get_pilot(self, pilot_id, headers):
        return self._request("GET", f"/v1/pilots/{pilot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    # ------------------------------------------------------------------
    # Flights
    # ------------------------------------------------------------------
    def create_flight(self, payload, headers):
        return self._request("POST", "/v1/flights", payload, headers)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/v1/flights/{flight_id}", headers=headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/v1/flights", headers=headers, params=params)

    def flight_event(self, flight_id, payload, headers):
        return self._request("POST", f"/v1/flights/{flight_id}/events", payload, headers)

    def select_launch_site(self, flight_id, payload, headers):
        return self._request(
            "POST", f"/v1/flights/{flight_id}/select-launch-site", payload, headers
        )

    def list_site_candidates(self, flight_id, headers):
        return self._request("GET", f"/v1/flights/{flight_id}/site-candidates", headers=headers)

    # ------------------------------------------------------------------
    # Reservations
    # ------------------------------------------------------------------
    def create_reservation(self, flight_id, payload, headers):
        return self._request("POST", f"/v1/flights/{flight_id}/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/v1/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/v1/reservations", headers=headers, params=params)

    def reservation_event(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/v1/reservations/{reservation_id}/events", payload, headers
        )

    # ------------------------------------------------------------------
    # Passengers (manifest)
    # ------------------------------------------------------------------
    def add_passenger(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/v1/reservations/{reservation_id}/passengers", payload, headers
        )

    def list_passengers(self, reservation_id, headers):
        return self._request(
            "GET", f"/v1/reservations/{reservation_id}/passengers", headers=headers
        )

    # ------------------------------------------------------------------
    # Weather briefings
    # ------------------------------------------------------------------
    def create_weather_briefing(self, flight_id, payload, headers):
        return self._request(
            "POST", f"/v1/flights/{flight_id}/weather-briefings", payload, headers
        )

    def list_weather_briefings(self, flight_id, headers):
        return self._request(
            "GET", f"/v1/flights/{flight_id}/weather-briefings", headers=headers
        )

    # ------------------------------------------------------------------
    # Chase assignments
    # ------------------------------------------------------------------
    def create_chase_assignment(self, flight_id, payload, headers):
        return self._request(
            "POST", f"/v1/flights/{flight_id}/chase-assignments", payload, headers
        )

    def list_chase_assignments(self, flight_id, headers):
        return self._request(
            "GET", f"/v1/flights/{flight_id}/chase-assignments", headers=headers
        )

    def chase_assignment_event(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/v1/chase-assignments/{assignment_id}/events", payload, headers
        )

    # ------------------------------------------------------------------
    # Refunds
    # ------------------------------------------------------------------
    def list_refunds(self, reservation_id, headers):
        return self._request("GET", f"/v1/reservations/{reservation_id}/refunds", headers=headers)

    def refund_event(self, refund_id, payload, headers):
        return self._request("POST", f"/v1/refunds/{refund_id}/events", payload, headers)

    # ------------------------------------------------------------------
    # Photo package records
    # ------------------------------------------------------------------
    def list_photo_packages(self, reservation_id, headers):
        return self._request(
            "GET", f"/v1/reservations/{reservation_id}/photo-packages", headers=headers
        )


api_client = ApiClient()
