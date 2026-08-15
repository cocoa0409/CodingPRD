"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Contract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def transition_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/transition", payload, headers)

    # --- BidItem ---
    def create_bid_item(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/bid-items", payload, headers)

    def list_bid_items(self, headers, params=None):
        return self._request("GET", "/bid-items", headers=headers, params=params)

    def get_bid_item(self, bid_item_id, headers):
        return self._request("GET", f"/bid-items/{bid_item_id}", headers=headers)

    # --- WorkPackage ---
    def create_work_package(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/work-packages", payload, headers)

    def list_work_packages(self, headers, params=None):
        return self._request("GET", "/work-packages", headers=headers, params=params)

    def get_work_package(self, work_package_id, headers):
        return self._request("GET", f"/work-packages/{work_package_id}", headers=headers)

    def transition_work_package(self, work_package_id, payload, headers):
        return self._request("POST", f"/work-packages/{work_package_id}/transition", payload, headers)

    # --- Crew / Equipment ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    # --- Assignment ---
    def create_assignment(self, work_package_id, payload, headers):
        return self._request("POST", f"/work-packages/{work_package_id}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def transition_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/transition", payload, headers)

    # --- ProductionEntry ---
    def create_production_entry(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/production-entries", payload, headers)

    def list_production_entries(self, headers, params=None):
        return self._request("GET", "/production-entries", headers=headers, params=params)

    def get_production_entry(self, production_entry_id, headers):
        return self._request("GET", f"/production-entries/{production_entry_id}", headers=headers)

    def resubmit_production_entry(self, production_entry_id, headers, payload=None):
        return self._request("POST", f"/production-entries/{production_entry_id}/resubmit", payload or {}, headers)

    def void_production_entry(self, production_entry_id, headers):
        return self._request("POST", f"/production-entries/{production_entry_id}/void", {}, headers)

    # --- StockItem ---
    def create_stock_item(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/stock-items", payload, headers)

    def create_stock_receipt(self, stock_item_id, payload, headers):
        return self._request("POST", f"/stock-items/{stock_item_id}/receipts", payload, headers)

    def list_stock_items(self, headers, params=None):
        return self._request("GET", "/stock-items", headers=headers, params=params)

    def get_stock_item(self, stock_item_id, headers):
        return self._request("GET", f"/stock-items/{stock_item_id}", headers=headers)

    # --- MaterialIssue ---
    def create_material_issue(self, work_package_id, payload, headers):
        return self._request("POST", f"/work-packages/{work_package_id}/material-issues", payload, headers)

    def list_material_issues(self, headers, params=None):
        return self._request("GET", "/material-issues", headers=headers, params=params)

    def get_material_issue(self, material_issue_id, headers):
        return self._request("GET", f"/material-issues/{material_issue_id}", headers=headers)

    def return_material_issue(self, material_issue_id, payload, headers):
        return self._request("POST", f"/material-issues/{material_issue_id}/return", payload, headers)

    def reconcile_material_issue(self, material_issue_id, payload, headers):
        return self._request("POST", f"/material-issues/{material_issue_id}/reconcile", payload, headers)

    # --- Inspection ---
    def create_inspection(self, work_package_id, payload, headers):
        return self._request("POST", f"/work-packages/{work_package_id}/inspections", payload, headers)

    def submit_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/submit", payload, headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    # --- OutageRequest ---
    def create_outage_request(self, work_package_id, payload, headers):
        return self._request("POST", f"/work-packages/{work_package_id}/outage-requests", payload, headers)

    def decide_outage_request(self, outage_request_id, payload, headers):
        return self._request("POST", f"/outage-requests/{outage_request_id}/decide", payload, headers)

    def request_change_outage_request(self, outage_request_id, payload, headers):
        return self._request("POST", f"/outage-requests/{outage_request_id}/request-change", payload, headers)

    def release_outage_request(self, outage_request_id, headers):
        return self._request("POST", f"/outage-requests/{outage_request_id}/release", {}, headers)

    def cancel_outage_request(self, outage_request_id, headers):
        return self._request("POST", f"/outage-requests/{outage_request_id}/cancel", {}, headers)

    def list_outage_requests(self, headers, params=None):
        return self._request("GET", "/outage-requests", headers=headers, params=params)

    def get_outage_request(self, outage_request_id, headers):
        return self._request("GET", f"/outage-requests/{outage_request_id}", headers=headers)

    # --- StormActivation ---
    def create_storm_activation(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/storm-activations", payload, headers)

    def convert_storm_activation(self, storm_activation_id, headers):
        return self._request("POST", f"/storm-activations/{storm_activation_id}/convert", {}, headers)

    def close_storm_activation(self, storm_activation_id, payload, headers):
        return self._request("POST", f"/storm-activations/{storm_activation_id}/close", payload, headers)

    def cancel_storm_activation(self, storm_activation_id, headers):
        return self._request("POST", f"/storm-activations/{storm_activation_id}/cancel", {}, headers)

    def list_storm_activations(self, headers, params=None):
        return self._request("GET", "/storm-activations", headers=headers, params=params)

    def get_storm_activation(self, storm_activation_id, headers):
        return self._request("GET", f"/storm-activations/{storm_activation_id}", headers=headers)

    # --- SafetyEvent ---
    def create_safety_event(self, work_package_id, payload, headers):
        return self._request("POST", f"/work-packages/{work_package_id}/safety-events", payload, headers)

    def transition_safety_event(self, safety_event_id, payload, headers):
        return self._request("POST", f"/safety-events/{safety_event_id}/transition", payload, headers)

    def list_safety_events(self, headers, params=None):
        return self._request("GET", "/safety-events", headers=headers, params=params)

    def get_safety_event(self, safety_event_id, headers):
        return self._request("GET", f"/safety-events/{safety_event_id}", headers=headers)

    # --- Invoice ---
    def create_invoice(self, work_package_id, payload, headers):
        return self._request("POST", f"/work-packages/{work_package_id}/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/transition", payload, headers)

    def get_billing_preview(self, work_package_id, headers, params=None):
        return self._request("GET", f"/work-packages/{work_package_id}/billing-preview",
                             headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
