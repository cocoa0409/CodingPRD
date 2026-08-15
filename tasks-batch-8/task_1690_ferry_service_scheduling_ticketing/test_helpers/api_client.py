"""API client: one method per endpoint defined in the PRD (all under /ferry)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/ferry/_clock/set_current_utc", payload, headers)

    # --- Routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/ferry/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/ferry/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/ferry/routes", headers=headers, params=params)

    def list_route_fare_schedules(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/ferry/routes/{route_id}/fare-schedules", headers=headers, params=params
        )

    def list_route_sailings(self, route_id, headers, params=None):
        return self._request(
            "GET", f"/ferry/routes/{route_id}/sailings", headers=headers, params=params
        )

    # --- Vessels ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/ferry/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/ferry/vessels/{vessel_id}", headers=headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/ferry/vessels", headers=headers, params=params)

    def set_vessel_out_of_service(self, vessel_id, headers):
        return self._request(
            "POST", f"/ferry/vessels/{vessel_id}/set-out-of-service", {}, headers
        )

    # --- Fare schedules ---
    def create_fare_schedule(self, route_id, payload, headers):
        return self._request(
            "POST", f"/ferry/routes/{route_id}/fare-schedules", payload, headers
        )

    def get_fare_schedule(self, fare_schedule_id, headers):
        return self._request(
            "GET", f"/ferry/fare-schedules/{fare_schedule_id}", headers=headers
        )

    def submit_fare_schedule(self, fare_schedule_id, payload, headers):
        return self._request(
            "POST", f"/ferry/fare-schedules/{fare_schedule_id}/submit", payload, headers
        )

    def approve_fare_schedule(self, fare_schedule_id, headers):
        return self._request(
            "POST", f"/ferry/fare-schedules/{fare_schedule_id}/approve", {}, headers
        )

    def return_fare_schedule_for_revision(self, fare_schedule_id, headers):
        return self._request(
            "POST",
            f"/ferry/fare-schedules/{fare_schedule_id}/return-for-revision",
            {},
            headers,
        )

    def reject_fare_schedule(self, fare_schedule_id, headers):
        return self._request(
            "POST", f"/ferry/fare-schedules/{fare_schedule_id}/reject", {}, headers
        )

    # --- Sailings ---
    def create_sailing(self, route_id, payload, headers):
        return self._request("POST", f"/ferry/routes/{route_id}/sailings", payload, headers)

    def get_sailing(self, sailing_id, headers):
        return self._request("GET", f"/ferry/sailings/{sailing_id}", headers=headers)

    def list_sailings(self, headers, params=None):
        return self._request("GET", "/ferry/sailings", headers=headers, params=params)

    def list_sailing_bookings(self, sailing_id, headers, params=None):
        return self._request(
            "GET", f"/ferry/sailings/{sailing_id}/bookings", headers=headers, params=params
        )

    def list_sailing_standby_queue(self, sailing_id, headers, params=None):
        return self._request(
            "GET",
            f"/ferry/sailings/{sailing_id}/standby-queue",
            headers=headers,
            params=params,
        )

    def list_sailing_crew_assignments(self, sailing_id, headers, params=None):
        return self._request(
            "GET",
            f"/ferry/sailings/{sailing_id}/crew-assignments",
            headers=headers,
            params=params,
        )

    def get_deck_projection(self, sailing_id, ratio, headers):
        return self._request(
            "GET",
            f"/ferry/sailings/{sailing_id}/deck-projection",
            headers=headers,
            params={"ratio": ratio},
        )

    def open_booking(self, sailing_id, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/open-booking", {}, headers
        )

    def close_booking(self, sailing_id, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/close-booking", {}, headers
        )

    def begin_boarding(self, sailing_id, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/begin-boarding", {}, headers
        )

    def depart_sailing(self, sailing_id, headers):
        return self._request("POST", f"/ferry/sailings/{sailing_id}/depart", {}, headers)

    def complete_sailing(self, sailing_id, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/complete", {}, headers
        )

    def cancel_sailing(self, sailing_id, payload, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/cancel", payload, headers
        )

    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/ferry/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/ferry/customers/{customer_id}", headers=headers)

    def list_customer_bookings(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/ferry/customers/{customer_id}/bookings", headers=headers, params=params
        )

    def list_customer_standby_queue(self, customer_id, headers, params=None):
        return self._request(
            "GET",
            f"/ferry/customers/{customer_id}/standby-queue",
            headers=headers,
            params=params,
        )

    # --- Bookings ---
    def create_booking(self, sailing_id, payload, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/bookings", payload, headers
        )

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/ferry/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/ferry/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/ferry/bookings/{booking_id}/confirm", {}, headers)

    def modify_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/ferry/bookings/{booking_id}/modify", payload, headers
        )

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/ferry/bookings/{booking_id}/cancel", {}, headers)

    def rebook_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/ferry/bookings/{booking_id}/rebook", payload, headers
        )

    def check_in_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/ferry/bookings/{booking_id}/check-in", {}, headers
        )

    def board_booking(self, booking_id, headers):
        return self._request("POST", f"/ferry/bookings/{booking_id}/board", {}, headers)

    # --- Standby queue ---
    def join_standby_queue(self, sailing_id, payload, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/standby-queue", payload, headers
        )

    def get_standby_entry(self, entry_id, headers):
        return self._request("GET", f"/ferry/standby-queue/{entry_id}", headers=headers)

    def leave_standby_queue(self, entry_id, headers):
        return self._request(
            "POST", f"/ferry/standby-queue/{entry_id}/leave", {}, headers
        )

    # --- Crew ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/ferry/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request(
            "GET", f"/ferry/crew-members/{crew_member_id}", headers=headers
        )

    def list_crew_member_assignments(self, crew_member_id, headers, params=None):
        return self._request(
            "GET",
            f"/ferry/crew-members/{crew_member_id}/crew-assignments",
            headers=headers,
            params=params,
        )

    def set_crew_off_duty(self, crew_member_id, headers):
        return self._request(
            "POST", f"/ferry/crew-members/{crew_member_id}/set-off-duty", {}, headers
        )

    def set_crew_available(self, crew_member_id, headers):
        return self._request(
            "POST", f"/ferry/crew-members/{crew_member_id}/set-available", {}, headers
        )

    def create_crew_assignment(self, sailing_id, payload, headers):
        return self._request(
            "POST", f"/ferry/sailings/{sailing_id}/crew-assignments", payload, headers
        )

    def release_crew_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/ferry/crew-assignments/{assignment_id}/release", {}, headers
        )

    def get_crew_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/ferry/crew-assignments/{assignment_id}", headers=headers
        )


api_client = ApiClient()
