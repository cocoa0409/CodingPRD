"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- TransitCenter ---
    def create_transit_center(self, payload, headers):
        return self._request("POST", "/delivery/transit-centers", payload, headers)

    def list_transit_centers(self, headers, params=None):
        return self._request("GET", "/delivery/transit-centers", headers=headers, params=params)

    def get_transit_center(self, center_id, headers):
        return self._request("GET", f"/delivery/transit-centers/{center_id}", headers=headers)

    def close_transit_center(self, center_id, headers):
        return self._request("POST", f"/delivery/transit-centers/{center_id}/close", {}, headers)

    def list_sorted_parcels(self, center_id, headers, params=None):
        return self._request("GET", f"/delivery/transit-centers/{center_id}/sorted-parcels", headers=headers, params=params)

    # --- Driver ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/delivery/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/delivery/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/delivery/drivers/{driver_id}", headers=headers)

    def suspend_driver(self, driver_id, headers):
        return self._request("POST", f"/delivery/drivers/{driver_id}/suspend", {}, headers)

    def list_driver_routes(self, driver_id, headers, params=None):
        return self._request("GET", f"/delivery/drivers/{driver_id}/routes", headers=headers, params=params)

    # --- Parcel ---
    def create_parcel(self, payload, headers):
        return self._request("POST", "/delivery/parcels", payload, headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/delivery/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/delivery/parcels/{parcel_id}", headers=headers)

    def sort_parcel(self, parcel_id, payload, headers):
        return self._request("POST", f"/delivery/parcels/{parcel_id}/sort", payload, headers)

    # --- DeliveryRoute ---
    def create_route(self, payload, headers):
        return self._request("POST", "/delivery/routes", payload, headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/delivery/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/delivery/routes/{route_id}", headers=headers)

    def get_route_manifest(self, route_id, headers):
        return self._request("GET", f"/delivery/routes/{route_id}/manifest", headers=headers)

    def dispatch_route(self, route_id, payload, headers):
        return self._request("POST", f"/delivery/routes/{route_id}/dispatch", payload, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/delivery/routes/{route_id}/complete", {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/delivery/routes/{route_id}/cancel", {}, headers)

    # --- DeliveryStop ---
    def create_stop(self, payload, headers):
        return self._request("POST", "/delivery/stops", payload, headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/delivery/stops", headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/delivery/stops/{stop_id}", headers=headers)

    def create_attempt(self, stop_id, payload, headers):
        return self._request("POST", f"/delivery/stops/{stop_id}/attempts", payload, headers)

    def list_attempts(self, stop_id, headers, params=None):
        return self._request("GET", f"/delivery/stops/{stop_id}/attempts", headers=headers, params=params)

    def reschedule_stop(self, stop_id, headers):
        return self._request("POST", f"/delivery/stops/{stop_id}/reschedule", {}, headers)

    def cancel_stop(self, stop_id, headers):
        return self._request("POST", f"/delivery/stops/{stop_id}/cancel", {}, headers)

    # --- Appointment ---
    def create_appointment(self, payload, headers):
        return self._request("POST", "/delivery/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/delivery/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/delivery/appointments/{appointment_id}", headers=headers)

    def apply_appointment(self, appointment_id, headers):
        return self._request("POST", f"/delivery/appointments/{appointment_id}/apply", {}, headers)

    def reject_appointment(self, appointment_id, headers):
        return self._request("POST", f"/delivery/appointments/{appointment_id}/reject", {}, headers)


api_client = ApiClient()
