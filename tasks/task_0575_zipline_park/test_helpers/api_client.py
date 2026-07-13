"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Course ---
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_course_time_slots(self, course_id, headers, params=None):
        return self._request("GET", f"/courses/{course_id}/time-slots",
                             headers=headers, params=params)

    # --- TimeSlot ---
    def create_time_slot(self, payload, headers):
        return self._request("POST", "/time-slots", payload, headers)

    def get_time_slot(self, ts_id, headers):
        return self._request("GET", f"/time-slots/{ts_id}", headers=headers)

    def open_time_slot(self, ts_id, headers):
        return self._request("POST", f"/time-slots/{ts_id}/open", {}, headers)

    def close_time_slot(self, ts_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/time-slots/{ts_id}/close", payload, headers)

    def complete_time_slot(self, ts_id, headers):
        return self._request("POST", f"/time-slots/{ts_id}/complete", {}, headers)

    def list_time_slot_groups(self, ts_id, headers, params=None):
        return self._request("GET", f"/time-slots/{ts_id}/groups",
                             headers=headers, params=params)

    # --- Guide ---
    def create_guide(self, payload, headers):
        return self._request("POST", "/guides", payload, headers)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/guides/{guide_id}", headers=headers)

    # --- GuideAssignment ---
    def create_guide_assignment(self, payload, headers):
        return self._request("POST", "/guide-assignments", payload, headers)

    def get_guide_assignment(self, ga_id, headers):
        return self._request("GET", f"/guide-assignments/{ga_id}", headers=headers)

    def list_guide_assignments(self, headers, params=None):
        return self._request("GET", "/guide-assignments", headers=headers, params=params)

    def cancel_guide_assignment(self, ga_id, headers):
        return self._request("POST", f"/guide-assignments/{ga_id}/cancel", {}, headers)

    # --- Participant ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, p_id, headers):
        return self._request("GET", f"/participants/{p_id}", headers=headers)

    def sign_waiver(self, p_id, payload, headers):
        return self._request("POST", f"/participants/{p_id}/waiver", payload, headers)

    def create_season_pass(self, p_id, payload, headers):
        return self._request("POST", f"/participants/{p_id}/season-passes",
                             payload, headers)

    def list_season_passes(self, p_id, headers, params=None):
        return self._request("GET", f"/participants/{p_id}/season-passes",
                             headers=headers, params=params)

    # --- GearItem ---
    def create_gear_item(self, payload, headers):
        return self._request("POST", "/gear-items", payload, headers)

    def get_gear_item(self, gi_id, headers):
        return self._request("GET", f"/gear-items/{gi_id}", headers=headers)

    # --- Group ---
    def create_group(self, payload, headers):
        return self._request("POST", "/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/groups/{group_id}", headers=headers)

    def cancel_group(self, group_id, headers):
        return self._request("POST", f"/groups/{group_id}/cancel", {}, headers)

    # --- Booking ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def checkin_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/check-in", {}, headers)

    def brief_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/brief", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def redeem_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/redeem", payload, headers)

    def list_incident_reports(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/incident-reports",
                             headers=headers, params=params)

    # --- GearCheckout ---
    def create_gear_checkout(self, payload, headers):
        return self._request("POST", "/gear-checkouts", payload, headers)

    def get_gear_checkout(self, co_id, headers):
        return self._request("GET", f"/gear-checkouts/{co_id}", headers=headers)

    def list_gear_checkouts(self, headers, params=None):
        return self._request("GET", "/gear-checkouts", headers=headers, params=params)

    def return_gear_checkout(self, co_id, headers):
        return self._request("POST", f"/gear-checkouts/{co_id}/return", {}, headers)

    # --- IncidentReport ---
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)


api_client = ApiClient()
