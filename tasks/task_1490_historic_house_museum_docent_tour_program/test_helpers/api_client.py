"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Rooms ---
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_room_routes(self, room_id, headers, params=None):
        return self._request("GET", f"/rooms/{room_id}/routes",
                             headers=headers, params=params)

    def list_room_incidents(self, room_id, headers, params=None):
        return self._request("GET", f"/rooms/{room_id}/incidents",
                             headers=headers, params=params)

    # --- Tour routes ---
    def create_tour_route(self, payload, headers):
        return self._request("POST", "/tour-routes", payload, headers)

    def list_tour_routes(self, headers, params=None):
        return self._request("GET", "/tour-routes", headers=headers, params=params)

    def get_tour_route(self, route_id, headers):
        return self._request("GET", f"/tour-routes/{route_id}", headers=headers)

    def activate_tour_route(self, route_id, headers):
        return self._request("POST", f"/tour-routes/{route_id}/activate",
                             headers=headers)

    def retire_tour_route(self, route_id, headers):
        return self._request("POST", f"/tour-routes/{route_id}/retire",
                             headers=headers)

    def list_route_script_versions(self, route_id, headers, params=None):
        return self._request("GET", f"/tour-routes/{route_id}/script-versions",
                             headers=headers, params=params)

    def list_route_tour_slots(self, route_id, headers, params=None):
        return self._request("GET", f"/tour-routes/{route_id}/tour-slots",
                             headers=headers, params=params)

    def get_route_survey_summary(self, route_id, headers):
        return self._request("GET", f"/tour-routes/{route_id}/survey-summary",
                             headers=headers)

    def list_route_docents(self, route_id, headers, params=None):
        return self._request("GET", f"/tour-routes/{route_id}/docents",
                             headers=headers, params=params)

    # --- Script versions ---
    def create_script_version(self, route_id, payload, headers):
        return self._request("POST", f"/tour-routes/{route_id}/script-versions",
                             payload, headers)

    def get_script_version(self, script_id, headers):
        return self._request("GET", f"/script-versions/{script_id}",
                             headers=headers)

    def submit_script_version(self, script_id, headers):
        return self._request("POST", f"/script-versions/{script_id}/submit",
                             headers=headers)

    def review_script_version(self, script_id, payload, headers):
        return self._request("POST", f"/script-versions/{script_id}/review",
                             payload, headers)

    def publish_script_version(self, script_id, payload, headers):
        return self._request("POST", f"/script-versions/{script_id}/publish",
                             payload, headers)

    # --- Tour slots ---
    def create_tour_slot(self, payload, headers):
        return self._request("POST", "/tour-slots", payload, headers)

    def get_tour_slot(self, slot_id, headers):
        return self._request("GET", f"/tour-slots/{slot_id}", headers=headers)

    def open_tour_slot(self, slot_id, headers):
        return self._request("POST", f"/tour-slots/{slot_id}/open",
                             headers=headers)

    def advance_tour_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/tour-slots/{slot_id}/advance",
                             payload, headers)

    def cancel_tour_slot(self, slot_id, headers):
        return self._request("POST", f"/tour-slots/{slot_id}/cancel",
                             headers=headers)

    def reschedule_tour_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/tour-slots/{slot_id}/reschedule",
                             payload, headers)

    def list_slot_bookings(self, slot_id, headers, params=None):
        return self._request("GET", f"/tour-slots/{slot_id}/bookings",
                             headers=headers, params=params)

    def list_slot_shifts(self, slot_id, headers, params=None):
        return self._request("GET", f"/tour-slots/{slot_id}/shifts",
                             headers=headers, params=params)

    def list_slot_incidents(self, slot_id, headers, params=None):
        return self._request("GET", f"/tour-slots/{slot_id}/incidents",
                             headers=headers, params=params)

    def list_slot_surveys(self, slot_id, headers, params=None):
        return self._request("GET", f"/tour-slots/{slot_id}/surveys",
                             headers=headers, params=params)

    # --- Docents ---
    def create_docent(self, payload, headers):
        return self._request("POST", "/docents", payload, headers)

    def get_docent(self, docent_id, headers):
        return self._request("GET", f"/docents/{docent_id}", headers=headers)

    def advance_docent(self, docent_id, payload, headers):
        return self._request("POST", f"/docents/{docent_id}/advance",
                             payload, headers)

    def deactivate_docent(self, docent_id, headers):
        return self._request("POST", f"/docents/{docent_id}/deactivate",
                             headers=headers)

    def log_training_record(self, docent_id, payload, headers):
        return self._request("POST", f"/docents/{docent_id}/training-records",
                             payload, headers)

    def list_docent_shifts(self, docent_id, headers, params=None):
        return self._request("GET", f"/docents/{docent_id}/shifts",
                             headers=headers, params=params)

    # --- Shift assignments ---
    def create_shift_assignment(self, payload, headers):
        return self._request("POST", "/shift-assignments", payload, headers)

    def confirm_shift_assignment(self, shift_id, headers):
        return self._request("POST", f"/shift-assignments/{shift_id}/confirm",
                             headers=headers)

    def decline_shift_assignment(self, shift_id, headers):
        return self._request("POST", f"/shift-assignments/{shift_id}/decline",
                             headers=headers)

    def resolve_shift_assignment(self, shift_id, payload, headers):
        return self._request("POST", f"/shift-assignments/{shift_id}/resolve",
                             payload, headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def renew_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/renew",
                             payload, headers)

    def list_member_bookings(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/bookings",
                             headers=headers, params=params)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm",
                             payload, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel",
                             headers=headers)

    def submit_survey(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/surveys",
                             payload, headers)

    def list_booking_surveys(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/surveys",
                             headers=headers, params=params)

    # --- Surveys ---
    def review_survey(self, survey_id, headers):
        return self._request("POST", f"/surveys/{survey_id}/review",
                             headers=headers)

    # --- Safety incidents ---
    def create_safety_incident(self, payload, headers):
        return self._request("POST", "/safety-incidents", payload, headers)

    def resolve_safety_incident(self, incident_id, headers):
        return self._request("POST", f"/safety-incidents/{incident_id}/resolve",
                             headers=headers)

    # --- System / test-driving ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_epoch(self, headers):
        return self._request("POST", "/_ops/run_epoch", headers=headers)


api_client = ApiClient()
