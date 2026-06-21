"""API client: one method per endpoint defined in the PRD.

Every path is mounted under the /workplace prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/workplace"


class ApiClient(GenericApiClient):
    # ---- Sites ----
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers=headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    # ---- Floors ----
    def create_floor(self, site_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/floors", payload, headers=headers)

    def list_floors(self, site_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites/{site_id}/floors", headers=headers, params=params)

    def get_floor(self, floor_id, headers):
        return self._request("GET", f"{PREFIX}/floors/{floor_id}", headers=headers)

    def get_floor_utilization(self, floor_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/floors/{floor_id}/utilization", headers=headers, params=params)

    # ---- Capacity policy ----
    def create_capacity_policy(self, floor_id, payload, headers):
        return self._request("POST", f"{PREFIX}/floors/{floor_id}/capacity-policy", payload, headers=headers)

    def list_capacity_policy(self, floor_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/floors/{floor_id}/capacity-policy", headers=headers, params=params)

    # ---- Neighborhoods ----
    def create_neighborhood(self, floor_id, payload, headers):
        return self._request("POST", f"{PREFIX}/floors/{floor_id}/neighborhoods", payload, headers=headers)

    def list_neighborhoods(self, floor_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/floors/{floor_id}/neighborhoods", headers=headers, params=params)

    def get_neighborhood(self, neighborhood_id, headers):
        return self._request("GET", f"{PREFIX}/neighborhoods/{neighborhood_id}", headers=headers)

    # ---- Seats ----
    def create_seat(self, neighborhood_id, payload, headers):
        return self._request("POST", f"{PREFIX}/neighborhoods/{neighborhood_id}/seats", payload, headers=headers)

    def list_seats(self, neighborhood_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/neighborhoods/{neighborhood_id}/seats", headers=headers, params=params)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"{PREFIX}/seats/{seat_id}", headers=headers)

    def seat_out_of_service(self, seat_id, headers):
        return self._request("POST", f"{PREFIX}/seats/{seat_id}/out-of-service", {}, headers=headers)

    def seat_restore(self, seat_id, headers):
        return self._request("POST", f"{PREFIX}/seats/{seat_id}/restore", {}, headers=headers)

    def seat_retire(self, seat_id, headers):
        return self._request("POST", f"{PREFIX}/seats/{seat_id}/retire", {}, headers=headers)

    # ---- Rooms ----
    def create_room(self, floor_id, payload, headers):
        return self._request("POST", f"{PREFIX}/floors/{floor_id}/rooms", payload, headers=headers)

    def list_rooms(self, floor_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/floors/{floor_id}/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"{PREFIX}/rooms/{room_id}", headers=headers)

    # ---- Employees ----
    def create_employee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employees", payload, headers=headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"{PREFIX}/employees/{employee_id}", headers=headers)

    def list_employee_no_show_events(self, employee_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/employees/{employee_id}/no-show-events", headers=headers, params=params)

    def reinstate_employee(self, employee_id, headers):
        return self._request("POST", f"{PREFIX}/employees/{employee_id}/reinstate", {}, headers=headers)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations", payload, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservations", headers=headers, params=params)

    def checkin_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/check-in", {}, headers=headers)

    def complete_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/complete", {}, headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/cancel", {}, headers=headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/release", {}, headers=headers)

    def list_reservation_check_ins(self, reservation_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}/check-ins", headers=headers, params=params)

    def list_reservation_no_show_events(self, reservation_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}/no-show-events", headers=headers, params=params)

    # ---- Amenity requests ----
    def create_amenity(self, reservation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reservations/{reservation_id}/amenities", payload, headers=headers)

    def list_amenities(self, reservation_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/reservations/{reservation_id}/amenities", headers=headers, params=params)

    def get_amenity(self, amenity_id, headers):
        return self._request("GET", f"{PREFIX}/amenity-requests/{amenity_id}", headers=headers)

    def approve_amenity(self, amenity_id, headers):
        return self._request("POST", f"{PREFIX}/amenity-requests/{amenity_id}/approve", {}, headers=headers)

    def deny_amenity(self, amenity_id, headers):
        return self._request("POST", f"{PREFIX}/amenity-requests/{amenity_id}/deny", {}, headers=headers)

    def cancel_amenity(self, amenity_id, headers):
        return self._request("POST", f"{PREFIX}/amenity-requests/{amenity_id}/cancel", {}, headers=headers)

    # ---- Visitor passes ----
    def create_visitor_pass(self, payload, headers):
        return self._request("POST", f"{PREFIX}/visitor-passes", payload, headers=headers)

    def get_visitor_pass(self, vp_id, headers):
        return self._request("GET", f"{PREFIX}/visitor-passes/{vp_id}", headers=headers)

    def list_visitor_passes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/visitor-passes", headers=headers, params=params)

    def visitor_pass_request_changes(self, vp_id, headers):
        return self._request("POST", f"{PREFIX}/visitor-passes/{vp_id}/request-changes", {}, headers=headers)

    def visitor_pass_resubmit(self, vp_id, payload, headers):
        return self._request("POST", f"{PREFIX}/visitor-passes/{vp_id}/resubmit", payload, headers=headers)

    def visitor_pass_approve(self, vp_id, headers):
        return self._request("POST", f"{PREFIX}/visitor-passes/{vp_id}/approve", {}, headers=headers)

    def visitor_pass_check_in(self, vp_id, headers):
        return self._request("POST", f"{PREFIX}/visitor-passes/{vp_id}/check-in", {}, headers=headers)

    def visitor_pass_complete(self, vp_id, headers):
        return self._request("POST", f"{PREFIX}/visitor-passes/{vp_id}/complete", {}, headers=headers)

    def visitor_pass_cancel(self, vp_id, headers):
        return self._request("POST", f"{PREFIX}/visitor-passes/{vp_id}/cancel", {}, headers=headers)

    # ---- Clock (test-driving) ----
    def set_clock(self, current_date, current_minute, headers):
        return self._request("POST", f"{PREFIX}/_clock/set",
                             {"current_date": current_date, "current_minute": current_minute},
                             headers=headers)

    def advance_no_show_sweep(self, headers, booking_date=None):
        payload = {} if booking_date is None else {"booking_date": booking_date}
        return self._request("POST", f"{PREFIX}/_clock/advance-no-show-sweep", payload, headers=headers)


api_client = ApiClient()
