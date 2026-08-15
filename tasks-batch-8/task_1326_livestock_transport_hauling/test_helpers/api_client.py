"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (CarrierAdmin-only test-driving capability) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/haul/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Shippers ---
    def create_shipper(self, payload, headers):
        return self._request("POST", "/haul/shippers", payload, headers)

    def list_shippers(self, headers, params=None):
        return self._request("GET", "/haul/shippers", headers=headers, params=params)

    def get_shipper(self, shipper_id, headers):
        return self._request("GET", f"/haul/shippers/{shipper_id}", headers=headers)

    # --- Drivers ---
    def create_driver(self, payload, headers):
        return self._request("POST", "/haul/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/haul/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/haul/drivers/{driver_id}", headers=headers)

    def create_duty_event(self, driver_id, payload, headers):
        return self._request("POST", f"/haul/drivers/{driver_id}/duty-events",
                             payload, headers)

    def list_duty_events(self, driver_id, headers, params=None):
        return self._request("GET", f"/haul/drivers/{driver_id}/duty-events",
                             headers=headers, params=params)

    # --- Trailers / compartments / washouts ---
    def create_trailer(self, payload, headers):
        return self._request("POST", "/haul/trailers", payload, headers)

    def list_trailers(self, headers, params=None):
        return self._request("GET", "/haul/trailers", headers=headers, params=params)

    def get_trailer(self, trailer_id, headers):
        return self._request("GET", f"/haul/trailers/{trailer_id}", headers=headers)

    def list_compartments(self, trailer_id, headers, params=None):
        return self._request("GET", f"/haul/trailers/{trailer_id}/compartments",
                             headers=headers, params=params)

    def create_washout(self, trailer_id, payload, headers):
        return self._request("POST", f"/haul/trailers/{trailer_id}/washouts",
                             payload, headers)

    def list_washouts(self, trailer_id, headers, params=None):
        return self._request("GET", f"/haul/trailers/{trailer_id}/washouts",
                             headers=headers, params=params)

    # --- Loads and planning ---
    def create_load(self, payload, headers):
        return self._request("POST", "/haul/loads", payload, headers)

    def list_loads(self, headers, params=None):
        return self._request("GET", "/haul/loads", headers=headers, params=params)

    def get_load(self, load_id, headers):
        return self._request("GET", f"/haul/loads/{load_id}", headers=headers)

    def create_allocation(self, load_id, payload, headers):
        return self._request("POST", f"/haul/loads/{load_id}/allocations",
                             payload, headers)

    def list_load_allocations(self, load_id, headers, params=None):
        return self._request("GET", f"/haul/loads/{load_id}/allocations",
                             headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/haul/allocations/{allocation_id}",
                             headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/haul/allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"/haul/allocations/{allocation_id}/release",
                             payload, headers)

    def finalize_plan(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/finalize-plan",
                             headers=headers)

    def reopen_plan(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/reopen-plan",
                             headers=headers)

    def cancel_load(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/cancel", headers=headers)

    # --- Compliance paperwork ---
    def create_health_paper(self, load_id, payload, headers):
        return self._request("POST", f"/haul/loads/{load_id}/health-papers",
                             payload, headers)

    def list_health_papers(self, load_id, headers, params=None):
        return self._request("GET", f"/haul/loads/{load_id}/health-papers",
                             headers=headers, params=params)

    def verify_health_paper(self, paper_id, headers):
        return self._request("POST", f"/haul/health-papers/{paper_id}/verify",
                             headers=headers)

    def reject_health_paper(self, paper_id, payload, headers):
        return self._request("POST", f"/haul/health-papers/{paper_id}/reject",
                             payload, headers)

    def create_brand_inspection(self, load_id, payload, headers):
        return self._request("POST", f"/haul/loads/{load_id}/brand-inspections",
                             payload, headers)

    def list_brand_inspections(self, load_id, headers, params=None):
        return self._request("GET", f"/haul/loads/{load_id}/brand-inspections",
                             headers=headers, params=params)

    def verify_brand_inspection(self, inspection_id, headers):
        return self._request("POST",
                             f"/haul/brand-inspections/{inspection_id}/verify",
                             headers=headers)

    def reject_brand_inspection(self, inspection_id, payload, headers):
        return self._request("POST",
                             f"/haul/brand-inspections/{inspection_id}/reject",
                             payload, headers)

    def verify_paperwork(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/verify-paperwork",
                             headers=headers)

    # --- Trip operations ---
    def assign_driver(self, load_id, payload, headers):
        return self._request("POST", f"/haul/loads/{load_id}/assign-driver",
                             payload, headers)

    def unassign_driver(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/unassign-driver",
                             headers=headers)

    def depart(self, load_id, payload, headers):
        return self._request("POST", f"/haul/loads/{load_id}/depart",
                             payload, headers)

    def create_weather_hold(self, load_id, payload, headers):
        return self._request("POST", f"/haul/loads/{load_id}/weather-holds",
                             payload, headers)

    def list_weather_holds(self, load_id, headers, params=None):
        return self._request("GET", f"/haul/loads/{load_id}/weather-holds",
                             headers=headers, params=params)

    def release_weather_hold(self, hold_id, headers):
        return self._request("POST", f"/haul/weather-holds/{hold_id}/release",
                             headers=headers)

    def rest_unload(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/rest-unload",
                             headers=headers)

    def resume_transit(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/resume-transit",
                             headers=headers)

    def arrive(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/arrive", headers=headers)

    def create_weight_ticket(self, load_id, payload, headers):
        return self._request("POST", f"/haul/loads/{load_id}/weight-tickets",
                             payload, headers)

    def list_weight_tickets(self, load_id, headers, params=None):
        return self._request("GET", f"/haul/loads/{load_id}/weight-tickets",
                             headers=headers, params=params)

    def deliver(self, load_id, headers):
        return self._request("POST", f"/haul/loads/{load_id}/deliver", headers=headers)

    # --- Welfare incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/haul/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/haul/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/haul/incidents/{incident_id}", headers=headers)

    def start_incident_review(self, incident_id, headers):
        return self._request("POST", f"/haul/incidents/{incident_id}/start-review",
                             headers=headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/haul/incidents/{incident_id}/close",
                             payload, headers)

    # --- Settlements ---
    def get_load_settlement(self, load_id, headers):
        return self._request("GET", f"/haul/loads/{load_id}/settlement",
                             headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/haul/settlements", headers=headers,
                             params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/haul/settlements/{settlement_id}",
                             headers=headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/haul/settlements/{settlement_id}/dispute",
                             payload, headers)

    def accept_original(self, settlement_id, headers):
        return self._request("POST",
                             f"/haul/settlements/{settlement_id}/accept-original",
                             headers=headers)

    def counter_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/haul/settlements/{settlement_id}/counter",
                             payload, headers)

    def redispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/haul/settlements/{settlement_id}/redispute",
                             payload, headers)

    def accept_counter(self, settlement_id, headers):
        return self._request("POST",
                             f"/haul/settlements/{settlement_id}/accept-counter",
                             headers=headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/haul/settlements/{settlement_id}/pay",
                             headers=headers)


api_client = ApiClient()
