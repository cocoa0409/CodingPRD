"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Accounts + clock ---
    def create_account(self, payload, headers):
        return self._request("POST", "/v1/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/v1/accounts/{account_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/v1/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/v1/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/v1/sites", headers=headers, params=params)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/v1/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/v1/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/v1/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/contracts/{contract_id}/activate", {}, headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/contracts/{contract_id}/suspend", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/contracts/{contract_id}/terminate", {}, headers)

    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/v1/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/v1/plans", headers=headers, params=params)

    def pause_plan(self, plan_id, headers):
        return self._request("POST", f"/v1/plans/{plan_id}/pause", {}, headers)

    # --- Crews ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/v1/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/v1/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/v1/crews", headers=headers, params=params)

    # --- Routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/v1/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/v1/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/v1/routes", headers=headers, params=params)

    def lock_route(self, route_id, headers):
        return self._request("POST", f"/v1/routes/{route_id}/lock", {}, headers)

    # --- Visits ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/v1/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/v1/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/v1/visits", headers=headers, params=params)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/start", {}, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/complete", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/cancel", {}, headers)

    def write_off_visit(self, visit_id, headers):
        return self._request("POST", f"/v1/visits/{visit_id}/write-off", {}, headers)

    # --- Add-ons ---
    def create_addon(self, payload, headers):
        return self._request("POST", "/v1/addons", payload, headers)

    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/v1/addons/{addon_id}", headers=headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/v1/addons", headers=headers, params=params)

    def approve_addon(self, addon_id, headers):
        return self._request("POST", f"/v1/addons/{addon_id}/approve", {}, headers)

    def reject_addon(self, addon_id, headers):
        return self._request("POST", f"/v1/addons/{addon_id}/reject", {}, headers)

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", "/v1/equipment", payload, headers)

    def get_equipment(self, asset_id, headers):
        return self._request("GET", f"/v1/equipment/{asset_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/v1/equipment", headers=headers, params=params)

    def maintenance_reset_equipment(self, asset_id, headers):
        return self._request("POST", f"/v1/equipment/{asset_id}/maintenance-reset", {}, headers)

    def decommission_equipment(self, asset_id, headers):
        return self._request("POST", f"/v1/equipment/{asset_id}/decommission", {}, headers)

    # --- Reservations ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/v1/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/v1/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/v1/reservations", headers=headers, params=params)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/v1/reservations/{reservation_id}/release", {}, headers)

    # --- Storm events ---
    def create_storm_event(self, payload, headers):
        return self._request("POST", "/v1/storm-events", payload, headers)

    def get_storm_event(self, event_id, headers):
        return self._request("GET", f"/v1/storm-events/{event_id}", headers=headers)

    def list_storm_events(self, headers, params=None):
        return self._request("GET", "/v1/storm-events", headers=headers, params=params)

    def dispatch_storm_event(self, event_id, headers):
        return self._request("POST", f"/v1/storm-events/{event_id}/dispatch", {}, headers)

    def abandon_storm_event(self, event_id, headers):
        return self._request("POST", f"/v1/storm-events/{event_id}/abandon", {}, headers)

    def resolve_storm_event(self, event_id, headers):
        return self._request("POST", f"/v1/storm-events/{event_id}/resolve", {}, headers)

    def stand_down_storm_event(self, event_id, headers):
        return self._request("POST", f"/v1/storm-events/{event_id}/stand-down", {}, headers)

    # --- Inspections ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/v1/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/v1/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/v1/inspections", headers=headers, params=params)

    def grade_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/v1/inspections/{inspection_id}/grade", payload, headers)

    def reopen_inspection(self, inspection_id, headers):
        return self._request("POST", f"/v1/inspections/{inspection_id}/reopen", {}, headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/v1/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/v1/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/issue", payload, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
