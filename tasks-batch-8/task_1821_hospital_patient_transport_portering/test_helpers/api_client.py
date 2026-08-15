"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock and time-driven sweep (supervisor-only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_sweeps(self, headers):
        return self._request("POST", "/_sweeps/run", {}, headers)

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------
    def create_location(self, payload, headers):
        return self._request("POST", "/transport/locations", payload, headers)

    # ------------------------------------------------------------------
    # Travel edges
    # ------------------------------------------------------------------
    def create_travel_edge(self, payload, headers):
        return self._request("POST", "/transport/travel-edges", payload, headers)

    def list_travel_edges(self, headers, params=None):
        return self._request("GET", "/transport/travel-edges",
                             headers=headers, params=params)

    def get_travel_edge(self, edge_id, headers):
        return self._request("GET", f"/transport/travel-edges/{edge_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Transporters
    # ------------------------------------------------------------------
    def create_transporter(self, payload, headers):
        return self._request("POST", "/transport/transporters", payload, headers)

    def list_transporters(self, headers, params=None):
        return self._request("GET", "/transport/transporters",
                             headers=headers, params=params)

    def get_transporter(self, transporter_id, headers):
        return self._request("GET", f"/transport/transporters/{transporter_id}",
                             headers=headers)

    def set_transporter_status(self, transporter_id, payload, headers):
        return self._request(
            "POST", f"/transport/transporters/{transporter_id}/set-status",
            payload, headers)

    def list_transporter_shifts(self, transporter_id, headers, params=None):
        return self._request(
            "GET", f"/transport/transporters/{transporter_id}/shifts",
            headers=headers, params=params)

    def list_transporter_offers(self, transporter_id, headers, params=None):
        return self._request(
            "GET", f"/transport/transporters/{transporter_id}/offers",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Equipment assets
    # ------------------------------------------------------------------
    def create_equipment_asset(self, payload, headers):
        return self._request("POST", "/transport/equipment-assets", payload, headers)

    def list_equipment_assets(self, headers, params=None):
        return self._request("GET", "/transport/equipment-assets",
                             headers=headers, params=params)

    def get_equipment_asset(self, asset_id, headers):
        return self._request("GET", f"/transport/equipment-assets/{asset_id}",
                             headers=headers)

    def set_equipment_service_status(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/transport/equipment-assets/{asset_id}/set-service-status",
            payload, headers)

    # ------------------------------------------------------------------
    # Transport requests
    # ------------------------------------------------------------------
    def create_request(self, payload, headers):
        return self._request("POST", "/transport/requests", payload, headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/transport/requests",
                             headers=headers, params=params)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/transport/requests/{request_id}",
                             headers=headers)

    def close_request(self, request_id, payload, headers):
        return self._request("POST", f"/transport/requests/{request_id}/close",
                             payload, headers)

    def create_offer(self, request_id, payload, headers):
        return self._request("POST", f"/transport/requests/{request_id}/offers",
                             payload, headers)

    def list_request_offers(self, request_id, headers, params=None):
        return self._request("GET", f"/transport/requests/{request_id}/offers",
                             headers=headers, params=params)

    def post_trip_event(self, request_id, payload, headers):
        return self._request("POST",
                             f"/transport/requests/{request_id}/trip-events",
                             payload, headers)

    def list_delay_records(self, request_id, headers, params=None):
        return self._request("GET",
                             f"/transport/requests/{request_id}/delay-records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Dispatch offers
    # ------------------------------------------------------------------
    def respond_offer(self, offer_id, payload, headers):
        return self._request("POST",
                             f"/transport/dispatch-offers/{offer_id}/respond",
                             payload, headers)

    # ------------------------------------------------------------------
    # Cleaning tasks
    # ------------------------------------------------------------------
    def advance_cleaning_task(self, task_id, payload, headers):
        return self._request("POST",
                             f"/transport/cleaning-tasks/{task_id}/advance",
                             payload, headers)

    def list_cleaning_tasks(self, headers, params=None):
        return self._request("GET", "/transport/cleaning-tasks",
                             headers=headers, params=params)

    def get_cleaning_task(self, task_id, headers):
        return self._request("GET", f"/transport/cleaning-tasks/{task_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Staffing shifts
    # ------------------------------------------------------------------
    def create_staffing_shift(self, payload, headers):
        return self._request("POST", "/transport/staffing-shifts", payload, headers)

    def set_shift_status(self, shift_id, payload, headers):
        return self._request("POST",
                             f"/transport/staffing-shifts/{shift_id}/set-status",
                             payload, headers)

    # ------------------------------------------------------------------
    # Demand curves and staffing adequacy
    # ------------------------------------------------------------------
    def create_demand_curve(self, payload, headers):
        return self._request("POST", "/transport/demand-curves", payload, headers)

    def get_staffing_adequacy(self, headers, params=None):
        return self._request("GET", "/transport/staffing/adequacy",
                             headers=headers, params=params)


api_client = ApiClient()
