"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customers (PRD §3.1) ──────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/power-rental/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/power-rental/customers/{customer_id}", headers=headers)

    # ─── Sites (PRD §3.1, §3.5) ────────────────────────────
    def create_site(self, payload, headers):
        return self._request("POST", "/power-rental/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/power-rental/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/power-rental/sites", headers=headers, params=params)

    def get_emissions_screening(self, site_id, headers):
        return self._request(
            "GET", f"/power-rental/sites/{site_id}/emissions-screening", headers=headers
        )

    # ─── Equipment units (PRD §3.2, §3.6) ──────────────────
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/power-rental/equipment-units", payload, headers)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/power-rental/equipment-units/{unit_id}", headers=headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/power-rental/equipment-units", headers=headers, params=params)

    def complete_maintenance(self, unit_id, headers):
        return self._request(
            "POST", f"/power-rental/equipment-units/{unit_id}/complete-maintenance",
            {}, headers,
        )

    def get_fuel_projection(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/power-rental/equipment-units/{unit_id}/fuel-projection",
            headers=headers, params=params,
        )

    # ─── Accessory kits (PRD §3.2) ─────────────────────────
    def create_accessory_kit(self, payload, headers):
        return self._request("POST", "/power-rental/accessory-kits", payload, headers)

    def get_accessory_kit(self, kit_id, headers):
        return self._request("GET", f"/power-rental/accessory-kits/{kit_id}", headers=headers)

    # ─── Rental contracts (PRD §3.3, §3.4, §3.5, §3.9) ─────
    def create_contract(self, payload, headers):
        return self._request("POST", "/power-rental/rental-contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/power-rental/rental-contracts/{contract_id}", headers=headers
        )

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/power-rental/rental-contracts", headers=headers, params=params)

    def size_load(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/size-load", payload, headers
        )

    def quote_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/quote", {}, headers
        )

    def revise_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/revise", {}, headers
        )

    def confirm_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/confirm", payload, headers
        )

    def cancel_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/cancel", {}, headers
        )

    def mobilize_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/mobilize", {}, headers
        )

    def start_rental(self, contract_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/start-rental", {}, headers
        )

    def off_hire_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/off-hire", {}, headers
        )

    def close_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/close", {}, headers
        )

    def add_line(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/power-rental/rental-contracts/{contract_id}/lines", payload, headers
        )

    # ─── Rental lines (PRD §3.3, §3.9) ─────────────────────
    def get_rental_line(self, line_id, headers):
        return self._request("GET", f"/power-rental/rental-lines/{line_id}", headers=headers)

    def list_rental_lines(self, headers, params=None):
        return self._request("GET", "/power-rental/rental-lines", headers=headers, params=params)

    def off_hire_line(self, line_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-lines/{line_id}/off-hire", {}, headers
        )

    def return_line(self, line_id, headers):
        return self._request(
            "POST", f"/power-rental/rental-lines/{line_id}/return", {}, headers
        )

    # ─── Permits (PRD §3.5) ────────────────────────────────
    def create_permit(self, payload, headers):
        return self._request("POST", "/power-rental/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/power-rental/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/power-rental/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/power-rental/permits/{permit_id}/submit", {}, headers
        )

    def record_permit_decision(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/power-rental/permits/{permit_id}/record-decision", payload, headers
        )

    def resubmit_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/power-rental/permits/{permit_id}/resubmit", {}, headers
        )

    # ─── Service visits (PRD §3.7) ─────────────────────────
    def create_service_visit(self, payload, headers):
        return self._request("POST", "/power-rental/service-visits", payload, headers)

    def get_service_visit(self, visit_id, headers):
        return self._request("GET", f"/power-rental/service-visits/{visit_id}", headers=headers)

    def list_service_visits(self, headers, params=None):
        return self._request("GET", "/power-rental/service-visits", headers=headers, params=params)

    def dispatch_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"/power-rental/service-visits/{visit_id}/dispatch", payload, headers
        )

    def arrive_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/power-rental/service-visits/{visit_id}/arrive", {}, headers
        )

    def complete_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/power-rental/service-visits/{visit_id}/complete", {}, headers
        )

    def cancel_visit(self, visit_id, headers):
        return self._request(
            "POST", f"/power-rental/service-visits/{visit_id}/cancel", {}, headers
        )

    # ─── Telemetry events (PRD §3.6) ───────────────────────
    def create_telemetry_event(self, payload, headers):
        return self._request("POST", "/power-rental/telemetry-events", payload, headers)

    def get_telemetry_event(self, event_id, headers):
        return self._request(
            "GET", f"/power-rental/telemetry-events/{event_id}", headers=headers
        )

    def list_telemetry_events(self, headers, params=None):
        return self._request(
            "GET", "/power-rental/telemetry-events", headers=headers, params=params
        )

    # ─── Incidents (PRD §3.8) ──────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/power-rental/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/power-rental/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/power-rental/incidents", headers=headers, params=params)

    def assess_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/power-rental/incidents/{incident_id}/assess", payload, headers
        )

    def waive_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/power-rental/incidents/{incident_id}/waive", {}, headers
        )

    # ─── Logical clock (PRD §2.5) ──────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
