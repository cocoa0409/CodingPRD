"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- ServiceProperty ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---- CustomerPreference ----
    def create_preference(self, payload, headers):
        return self._request("POST", "/preferences", payload, headers)

    def get_preference(self, preference_id, headers):
        return self._request("GET", f"/preferences/{preference_id}", headers=headers)

    def list_preferences(self, headers, params=None):
        return self._request("GET", "/preferences", headers=headers, params=params)

    # ---- ServiceContract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/suspend", {}, headers)

    def close_season(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/close-season", {}, headers)

    def list_contract_invoices(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/invoices", headers=headers, params=params)

    def list_contract_visits(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/visits", headers=headers, params=params)

    # ---- ServiceRoute ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def reopen_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/reopen", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", {}, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    def list_route_crews(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/crews", headers=headers, params=params)

    def list_route_equipment(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/equipment", headers=headers, params=params)

    # ---- RouteStop ----
    def create_route_stop(self, payload, headers):
        return self._request("POST", "/route-stops", payload, headers)

    def get_route_stop(self, stop_id, headers):
        return self._request("GET", f"/route-stops/{stop_id}", headers=headers)

    def list_route_stops_filtered(self, headers, params=None):
        return self._request("GET", "/route-stops", headers=headers, params=params)

    # ---- Crew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    # ---- Equipment ----
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def rotate_equipment(self, equipment_id, payload, headers):
        return self._request("POST", f"/equipment/{equipment_id}/rotate", payload, headers)

    def start_maintenance(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/start-maintenance", {}, headers)

    def complete_maintenance(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/complete-maintenance", {}, headers)

    def get_wear_estimate(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}/wear-estimate", headers=headers)

    # ---- WeatherReading ----
    def create_weather_reading(self, payload, headers):
        return self._request("POST", "/weather-readings", payload, headers)

    def get_weather_reading(self, reading_id, headers):
        return self._request("GET", f"/weather-readings/{reading_id}", headers=headers)

    def process_weather_reading(self, reading_id, payload, headers):
        return self._request("POST", f"/weather-readings/{reading_id}/process", payload, headers)

    # ---- ServiceVisit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def dispatch_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/dispatch", {}, headers)

    def complete_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/visits/{visit_id}/complete", payload or {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    # ---- SkipRequest ----
    def create_skip_request(self, payload, headers):
        return self._request("POST", "/skip-requests", payload, headers)

    def get_skip_request(self, skip_id, headers):
        return self._request("GET", f"/skip-requests/{skip_id}", headers=headers)

    def list_skip_requests(self, headers, params=None):
        return self._request("GET", "/skip-requests", headers=headers, params=params)

    def approve_skip_request(self, skip_id, headers):
        return self._request("POST", f"/skip-requests/{skip_id}/approve", {}, headers)

    def reject_skip_request(self, skip_id, headers):
        return self._request("POST", f"/skip-requests/{skip_id}/reject", {}, headers)

    # ---- SeasonInvoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)


api_client = ApiClient()
