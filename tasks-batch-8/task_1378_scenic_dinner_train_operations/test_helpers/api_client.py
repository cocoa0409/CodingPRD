"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Track rights agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/railroad/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/railroad/agreements/{agreement_id}", headers=headers)

    def agreement_event(self, agreement_id, payload, headers):
        return self._request("POST", f"/railroad/agreements/{agreement_id}/events", payload, headers)

    def list_agreement_slots(self, agreement_id, headers, params=None):
        return self._request("GET", f"/railroad/agreements/{agreement_id}/slots", headers=headers, params=params)

    # --- Operating slots ---
    def create_slot(self, payload, headers):
        return self._request("POST", "/railroad/slots", payload, headers)

    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/railroad/slots/{slot_id}", headers=headers)

    # --- Rolling stock ---
    def create_rolling_stock(self, payload, headers):
        return self._request("POST", "/railroad/rolling-stock", payload, headers)

    def get_rolling_stock(self, stock_id, headers):
        return self._request("GET", f"/railroad/rolling-stock/{stock_id}", headers=headers)

    def rolling_stock_event(self, stock_id, payload, headers):
        return self._request("POST", f"/railroad/rolling-stock/{stock_id}/events", payload, headers)

    def list_stock_work_orders(self, stock_id, headers, params=None):
        return self._request("GET", f"/railroad/rolling-stock/{stock_id}/work-orders", headers=headers, params=params)

    # --- Maintenance work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/railroad/work-orders", payload, headers)

    def work_order_event(self, work_order_id, payload, headers):
        return self._request("POST", f"/railroad/work-orders/{work_order_id}/events", payload, headers)

    # --- Excursions ---
    def create_excursion(self, payload, headers):
        return self._request("POST", "/railroad/excursions", payload, headers)

    def get_excursion(self, excursion_id, headers):
        return self._request("GET", f"/railroad/excursions/{excursion_id}", headers=headers)

    def list_excursions(self, headers, params=None):
        return self._request("GET", "/railroad/excursions", headers=headers, params=params)

    def excursion_event(self, excursion_id, payload, headers):
        return self._request("POST", f"/railroad/excursions/{excursion_id}/events", payload, headers)

    def get_excursion_manifests(self, excursion_id, headers, params=None):
        return self._request("GET", f"/railroad/excursions/{excursion_id}/provisioning-manifests", headers=headers, params=params)

    # --- Car assignments ---
    def create_car_assignment(self, payload, headers):
        return self._request("POST", "/railroad/car-assignments", payload, headers)

    def get_car_assignment(self, assignment_id, headers):
        return self._request("GET", f"/railroad/car-assignments/{assignment_id}", headers=headers)

    def list_car_assignments(self, headers, params=None):
        return self._request("GET", "/railroad/car-assignments", headers=headers, params=params)

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/railroad/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/railroad/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/railroad/bookings", headers=headers, params=params)

    def booking_event(self, booking_id, payload, headers):
        return self._request("POST", f"/railroad/bookings/{booking_id}/events", payload, headers)

    # --- Crew members ---
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/railroad/crew-members", payload, headers)

    def get_crew_member(self, member_id, headers):
        return self._request("GET", f"/railroad/crew-members/{member_id}", headers=headers)

    def crew_member_event(self, member_id, payload, headers):
        return self._request("POST", f"/railroad/crew-members/{member_id}/events", payload, headers)

    # --- Crew assignments ---
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/railroad/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/railroad/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/railroad/crew-assignments", headers=headers, params=params)

    def crew_assignment_event(self, assignment_id, payload, headers):
        return self._request("POST", f"/railroad/crew-assignments/{assignment_id}/events", payload, headers)

    # --- Provisioning manifests ---
    def get_manifest(self, manifest_id, headers):
        return self._request("GET", f"/railroad/manifests/{manifest_id}", headers=headers)

    def manifest_event(self, manifest_id, payload, headers):
        return self._request("POST", f"/railroad/manifests/{manifest_id}/events", payload, headers)

    # --- Rain-checks ---
    def get_rain_check(self, rain_check_id, headers):
        return self._request("GET", f"/railroad/rain-checks/{rain_check_id}", headers=headers)

    def list_rain_checks(self, headers, params=None):
        return self._request("GET", "/railroad/rain-checks", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/railroad/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
