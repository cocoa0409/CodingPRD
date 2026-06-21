"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Marina ----
    def create_marina(self, payload, headers):
        return self._request("POST", "/marinas", payload, headers)

    def get_marina(self, marina_id, headers):
        return self._request("GET", f"/marinas/{marina_id}", headers=headers)

    def list_marinas(self, headers, params=None):
        return self._request("GET", "/marinas", headers=headers, params=params)

    def set_marina_status(self, marina_id, payload, headers):
        return self._request("POST", f"/marinas/{marina_id}/set-status", payload, headers)

    # ---- DockSlot ----
    def create_dock_slot(self, payload, headers):
        return self._request("POST", "/dock-slots", payload, headers)

    def get_dock_slot(self, slot_id, headers):
        return self._request("GET", f"/dock-slots/{slot_id}", headers=headers)

    def list_dock_slots(self, headers, params=None):
        return self._request("GET", "/dock-slots", headers=headers, params=params)

    def decommission_dock_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"/dock-slots/{slot_id}/decommission", payload or {}, headers)

    # ---- Boat ----
    def create_boat(self, payload, headers):
        return self._request("POST", "/boats", payload, headers)

    def get_boat(self, boat_id, headers):
        return self._request("GET", f"/boats/{boat_id}", headers=headers)

    def list_boats(self, headers, params=None):
        return self._request("GET", "/boats", headers=headers, params=params)

    def set_boat_status(self, boat_id, payload, headers):
        return self._request("POST", f"/boats/{boat_id}/set-status", payload, headers)

    # ---- Captain ----
    def create_captain(self, payload, headers):
        return self._request("POST", "/captains", payload, headers)

    def get_captain(self, captain_id, headers):
        return self._request("GET", f"/captains/{captain_id}", headers=headers)

    def list_captains(self, headers, params=None):
        return self._request("GET", "/captains", headers=headers, params=params)

    def set_captain_status(self, captain_id, payload, headers):
        return self._request("POST", f"/captains/{captain_id}/set-status", payload, headers)

    # ---- Mate ----
    def create_mate(self, payload, headers):
        return self._request("POST", "/mates", payload, headers)

    def get_mate(self, mate_id, headers):
        return self._request("GET", f"/mates/{mate_id}", headers=headers)

    def list_mates(self, headers, params=None):
        return self._request("GET", "/mates", headers=headers, params=params)

    # ---- Permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Charter ----
    def create_charter(self, payload, headers):
        return self._request("POST", "/charters", payload, headers)

    def get_charter(self, charter_id, headers):
        return self._request("GET", f"/charters/{charter_id}", headers=headers)

    def list_charters(self, headers, params=None):
        return self._request("GET", "/charters", headers=headers, params=params)

    def schedule_charter(self, charter_id, headers, payload=None):
        return self._request("POST", f"/charters/{charter_id}/schedule", payload or {}, headers)

    def weather_hold_charter(self, charter_id, headers, payload=None):
        return self._request("POST", f"/charters/{charter_id}/weather-hold", payload or {}, headers)

    def reschedule_charter(self, charter_id, payload, headers):
        return self._request("POST", f"/charters/{charter_id}/reschedule", payload, headers)

    def sail_charter(self, charter_id, headers, payload=None):
        return self._request("POST", f"/charters/{charter_id}/sail", payload or {}, headers)

    def settle_charter(self, charter_id, headers, payload=None):
        return self._request("POST", f"/charters/{charter_id}/settle", payload or {}, headers)

    def cancel_charter(self, charter_id, headers, payload=None):
        return self._request("POST", f"/charters/{charter_id}/cancel", payload or {}, headers)

    # ---- CrewAssignment ----
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/crew-assignments", headers=headers, params=params)

    # ---- SlotReservation ----
    def create_slot_reservation(self, payload, headers):
        return self._request("POST", "/slot-reservations", payload, headers)

    def get_slot_reservation(self, reservation_id, headers):
        return self._request("GET", f"/slot-reservations/{reservation_id}", headers=headers)

    def list_slot_reservations(self, headers, params=None):
        return self._request("GET", "/slot-reservations", headers=headers, params=params)

    # ---- Booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def pay_deposit(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/pay-deposit", payload, headers)

    def cancel_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload or {}, headers)

    # ---- AddOnLine ----
    def create_add_on_line(self, payload, headers):
        return self._request("POST", "/add-on-lines", payload, headers)

    def get_add_on_line(self, add_on_id, headers):
        return self._request("GET", f"/add-on-lines/{add_on_id}", headers=headers)

    def list_add_on_lines(self, headers, params=None):
        return self._request("GET", "/add-on-lines", headers=headers, params=params)

    def fulfill_add_on_line(self, add_on_id, headers, payload=None):
        return self._request("POST", f"/add-on-lines/{add_on_id}/fulfill", payload or {}, headers)

    # ---- CatchReport ----
    def create_catch_report(self, payload, headers):
        return self._request("POST", "/catch-reports", payload, headers)

    def get_catch_report(self, report_id, headers):
        return self._request("GET", f"/catch-reports/{report_id}", headers=headers)

    def list_catch_reports(self, headers, params=None):
        return self._request("GET", "/catch-reports", headers=headers, params=params)

    # ---- Test-driving clock (PRD §3.9) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
