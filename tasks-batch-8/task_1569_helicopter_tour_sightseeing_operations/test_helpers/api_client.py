"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Base ---
    def create_base(self, payload, headers):
        return self._request("POST", "/bases", payload, headers)

    def get_base(self, base_id, headers):
        return self._request("GET", f"/bases/{base_id}", headers=headers)

    def update_base(self, base_id, payload, headers):
        return self._request("PATCH", f"/bases/{base_id}", payload, headers)

    def run_ops(self, base_id, headers):
        return self._request("POST", f"/bases/{base_id}/run-ops", {}, headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def route_event(self, route_id, payload, headers):
        return self._request("POST", f"/routes/{route_id}/events", payload, headers)

    # --- Season ---
    def create_season(self, payload, headers):
        return self._request("POST", "/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def season_event(self, season_id, payload, headers):
        return self._request("POST", f"/seasons/{season_id}/events", payload, headers)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def aircraft_event(self, aircraft_id, payload, headers):
        return self._request("POST", f"/aircraft/{aircraft_id}/events", payload, headers)

    # --- Pilot ---
    def create_pilot(self, payload, headers):
        return self._request("POST", "/pilots", payload, headers)

    def list_pilots(self, headers, params=None):
        return self._request("GET", "/pilots", headers=headers, params=params)

    def get_pilot(self, pilot_id, headers):
        return self._request("GET", f"/pilots/{pilot_id}", headers=headers)

    # --- DutyDay ---
    def list_duty_days(self, headers, params=None):
        return self._request("GET", "/duty-days", headers=headers, params=params)

    def get_duty_day(self, duty_day_id, headers):
        return self._request("GET", f"/duty-days/{duty_day_id}", headers=headers)

    # --- Flight ---
    def create_flight(self, payload, headers):
        return self._request("POST", "/flights", payload, headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/flights", headers=headers, params=params)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/flights/{flight_id}", headers=headers)

    def update_flight_assignment(self, flight_id, payload, headers):
        return self._request("PATCH", f"/flights/{flight_id}/assignment", payload, headers)

    def flight_event(self, flight_id, payload, headers):
        return self._request("POST", f"/flights/{flight_id}/events", payload, headers)

    def close_manifest(self, flight_id, payload, headers):
        return self._request("POST", f"/flights/{flight_id}/close-manifest", payload, headers)

    # --- Booking ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def apply_credit(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/apply-credit", payload, headers)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", payload, headers)

    def booking_event(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/events", payload, headers)

    def move_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/move", payload, headers)

    # --- Passenger ---
    def list_passengers(self, headers, params=None):
        return self._request("GET", "/passengers", headers=headers, params=params)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"/passengers/{passenger_id}", headers=headers)

    def passenger_event(self, passenger_id, payload, headers):
        return self._request("POST", f"/passengers/{passenger_id}/events", payload, headers)

    # --- RebookingCredit ---
    def list_credits(self, headers, params=None):
        return self._request("GET", "/credits", headers=headers, params=params)

    def get_credit(self, credit_id, headers):
        return self._request("GET", f"/credits/{credit_id}", headers=headers)

    # --- WeatherObservation ---
    def create_weather_observation(self, payload, headers):
        return self._request("POST", "/weather-observations", payload, headers)

    def list_weather_observations(self, headers, params=None):
        return self._request("GET", "/weather-observations", headers=headers, params=params)

    def get_weather_observation(self, observation_id, headers):
        return self._request("GET", f"/weather-observations/{observation_id}", headers=headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def complaint_event(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/events", payload, headers)

    # --- Logical clock (test-driving capability, PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
