"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/soaring/_clock/set_current_utc", payload, headers)

    # --- MembershipTier ---
    def create_tier(self, payload, headers):
        return self._request("POST", "/soaring/tiers", payload, headers)

    def list_tiers(self, headers, params=None):
        return self._request("GET", "/soaring/tiers", headers=headers, params=params)

    def get_tier(self, tier_id, headers):
        return self._request("GET", f"/soaring/tiers/{tier_id}", headers=headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/soaring/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/soaring/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/soaring/members/{member_id}", headers=headers)

    def change_member_tier(self, member_id, payload, headers):
        return self._request("POST", f"/soaring/members/{member_id}/tier", payload, headers)

    def record_payment(self, member_id, payload, headers):
        return self._request("POST", f"/soaring/members/{member_id}/payments", payload, headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/soaring/members/{member_id}/suspend", {}, headers)

    def resign_member(self, member_id, headers):
        return self._request("POST", f"/soaring/members/{member_id}/resign", {}, headers)

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/soaring/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/soaring/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/soaring/aircraft/{aircraft_id}", headers=headers)

    def ground_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/soaring/aircraft/{aircraft_id}/ground", {}, headers)

    def unground_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/soaring/aircraft/{aircraft_id}/unground", {}, headers)

    def retire_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/soaring/aircraft/{aircraft_id}/retire", {}, headers)

    def create_maintenance_record(self, aircraft_id, payload, headers):
        return self._request(
            "POST", f"/soaring/aircraft/{aircraft_id}/maintenance-records", payload, headers
        )

    def list_maintenance_records(self, aircraft_id, headers, params=None):
        return self._request(
            "GET", f"/soaring/aircraft/{aircraft_id}/maintenance-records",
            headers=headers, params=params,
        )

    # --- InstructorAvailability ---
    def create_availability(self, payload, headers):
        return self._request("POST", "/soaring/instructor-availability", payload, headers)

    def list_availability(self, headers, params=None):
        return self._request("GET", "/soaring/instructor-availability", headers=headers, params=params)

    def get_availability(self, availability_id, headers):
        return self._request(
            "GET", f"/soaring/instructor-availability/{availability_id}", headers=headers
        )

    def cancel_availability(self, availability_id, headers):
        return self._request(
            "POST", f"/soaring/instructor-availability/{availability_id}/cancel", {}, headers
        )

    # --- Reservation ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/soaring/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/soaring/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/soaring/reservations/{reservation_id}", headers=headers)

    def checkout_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/soaring/reservations/{reservation_id}/checkout", {}, headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/soaring/reservations/{reservation_id}/cancel", {}, headers
        )

    # --- TowSlot ---
    def create_tow_slot(self, payload, headers):
        return self._request("POST", "/soaring/tow-slots", payload, headers)

    def list_tow_slots(self, headers, params=None):
        return self._request("GET", "/soaring/tow-slots", headers=headers, params=params)

    def get_tow_slot(self, slot_id, headers):
        return self._request("GET", f"/soaring/tow-slots/{slot_id}", headers=headers)

    def cancel_tow_slot(self, slot_id, headers):
        return self._request("POST", f"/soaring/tow-slots/{slot_id}/cancel", {}, headers)

    # --- Flight ---
    def create_flight(self, payload, headers):
        return self._request("POST", "/soaring/flights", payload, headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/soaring/flights", headers=headers, params=params)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/soaring/flights/{flight_id}", headers=headers)

    def land_flight(self, flight_id, payload, headers):
        return self._request("POST", f"/soaring/flights/{flight_id}/land", payload, headers)

    def reconcile_flight(self, flight_id, headers):
        return self._request("POST", f"/soaring/flights/{flight_id}/reconcile", {}, headers)

    def void_flight(self, flight_id, headers):
        return self._request("POST", f"/soaring/flights/{flight_id}/void", {}, headers)

    # --- DutyRosterSlot ---
    def create_duty_slot(self, payload, headers):
        return self._request("POST", "/soaring/duty-roster", payload, headers)

    def list_duty_slots(self, headers, params=None):
        return self._request("GET", "/soaring/duty-roster", headers=headers, params=params)

    def get_duty_slot(self, slot_id, headers):
        return self._request("GET", f"/soaring/duty-roster/{slot_id}", headers=headers)

    def confirm_duty_slot(self, slot_id, headers):
        return self._request("POST", f"/soaring/duty-roster/{slot_id}/confirm", {}, headers)

    def propose_swap(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/soaring/duty-roster/{slot_id}/propose-swap", payload, headers
        )

    def accept_swap(self, slot_id, headers):
        return self._request("POST", f"/soaring/duty-roster/{slot_id}/accept-swap", {}, headers)

    def decline_swap(self, slot_id, headers):
        return self._request("POST", f"/soaring/duty-roster/{slot_id}/decline-swap", {}, headers)

    # --- StudentProgress ---
    def create_progress(self, payload, headers):
        return self._request("POST", "/soaring/student-progress", payload, headers)

    def list_progress(self, headers, params=None):
        return self._request("GET", "/soaring/student-progress", headers=headers, params=params)

    def get_progress(self, progress_id, headers):
        return self._request("GET", f"/soaring/student-progress/{progress_id}", headers=headers)

    def signoff_progress(self, progress_id, headers):
        return self._request(
            "POST", f"/soaring/student-progress/{progress_id}/signoff", {}, headers
        )

    def verify_progress(self, progress_id, headers):
        return self._request(
            "POST", f"/soaring/student-progress/{progress_id}/verify", {}, headers
        )

    def return_for_rework(self, progress_id, headers):
        return self._request(
            "POST", f"/soaring/student-progress/{progress_id}/return-for-rework", {}, headers
        )

    def reject_progress(self, progress_id, headers):
        return self._request(
            "POST", f"/soaring/student-progress/{progress_id}/reject", {}, headers
        )

    # --- RetrieveRequest ---
    def create_retrieve(self, payload, headers):
        return self._request("POST", "/soaring/retrieves", payload, headers)

    def list_retrieves(self, headers, params=None):
        return self._request("GET", "/soaring/retrieves", headers=headers, params=params)

    def get_retrieve(self, retrieve_id, headers):
        return self._request("GET", f"/soaring/retrieves/{retrieve_id}", headers=headers)

    def assign_crew(self, retrieve_id, payload, headers):
        return self._request(
            "POST", f"/soaring/retrieves/{retrieve_id}/assign-crew", payload, headers
        )

    def complete_retrieve(self, retrieve_id, headers):
        return self._request("POST", f"/soaring/retrieves/{retrieve_id}/complete", {}, headers)

    def cancel_retrieve(self, retrieve_id, headers):
        return self._request("POST", f"/soaring/retrieves/{retrieve_id}/cancel", {}, headers)

    # --- Ops-day close ---
    def close_ops_day(self, headers):
        return self._request("POST", "/soaring/ops-day/close", {}, headers)


api_client = ApiClient()
