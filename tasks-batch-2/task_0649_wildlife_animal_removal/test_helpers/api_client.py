"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- SpeciesProfile ----
    def create_species_profile(self, payload, headers):
        return self._request("POST", "/species-profiles", payload, headers)

    def get_species_profile(self, species_id, headers):
        return self._request("GET", f"/species-profiles/{species_id}", headers=headers)

    def list_species_profiles(self, headers, params=None):
        return self._request("GET", "/species-profiles", headers=headers, params=params)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    # ---- ServiceAccount ----
    def create_service_account(self, payload, headers):
        return self._request("POST", "/service-accounts", payload, headers)

    def get_service_account(self, account_id, headers):
        return self._request("GET", f"/service-accounts/{account_id}", headers=headers)

    # ---- Property ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # ---- Inspection ----
    def create_inspection(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/inspections", payload, headers)

    def list_property_inspections(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def complete_inspection(self, property_id, inspection_id, headers):
        return self._request("POST", f"/properties/{property_id}/inspections/{inspection_id}/complete", {}, headers)

    def cancel_inspection(self, property_id, inspection_id, headers):
        return self._request("POST", f"/properties/{property_id}/inspections/{inspection_id}/cancel", {}, headers)

    # ---- EntryPoint ----
    def create_entry_point(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/entry-points", payload, headers)

    def list_inspection_entry_points(self, inspection_id, headers, params=None):
        return self._request("GET", f"/inspections/{inspection_id}/entry-points", headers=headers, params=params)

    def get_entry_point(self, entry_point_id, headers):
        return self._request("GET", f"/entry-points/{entry_point_id}", headers=headers)

    def list_entry_points(self, headers, params=None):
        return self._request("GET", "/entry-points", headers=headers, params=params)

    # ---- Quote ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def create_line_item(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/line-items", payload, headers)

    def list_quote_line_items(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", {}, headers)

    def request_revision_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/request-revision", {}, headers)

    def reopen_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/reopen", {}, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers)

    def decline_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/decline", {}, headers)

    # ---- WorkOrder ----
    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/cancel", payload, headers)

    # ---- Permit ----
    def list_work_order_permits(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def approve_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/approve", payload, headers)

    def deny_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/deny", {}, headers)

    # ---- TrapPlacement ----
    def create_trap_placement(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/trap-placements", payload, headers)

    def list_work_order_trap_placements(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/trap-placements", headers=headers, params=params)

    def get_trap_placement(self, trap_placement_id, headers):
        return self._request("GET", f"/trap-placements/{trap_placement_id}", headers=headers)

    def list_trap_placements(self, headers, params=None):
        return self._request("GET", "/trap-placements", headers=headers, params=params)

    def create_capture(self, trap_placement_id, payload, headers):
        return self._request("POST", f"/trap-placements/{trap_placement_id}/captures", payload, headers)

    def pull_trap_placement(self, trap_placement_id, headers):
        return self._request("POST", f"/trap-placements/{trap_placement_id}/pull", {}, headers)

    def list_trap_captures(self, trap_placement_id, headers, params=None):
        return self._request("GET", f"/trap-placements/{trap_placement_id}/captures", headers=headers, params=params)

    # ---- ExclusionRepair ----
    def create_exclusion_repair(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/exclusion-repairs", payload, headers)

    def list_work_order_exclusion_repairs(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/exclusion-repairs", headers=headers, params=params)

    def get_exclusion_repair(self, repair_id, headers):
        return self._request("GET", f"/exclusion-repairs/{repair_id}", headers=headers)

    def list_exclusion_repairs(self, headers, params=None):
        return self._request("GET", "/exclusion-repairs", headers=headers, params=params)

    def complete_exclusion_repair(self, work_order_id, repair_id, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/exclusion-repairs/{repair_id}/complete", {}, headers)

    # ---- MonitoringVisit ----
    def create_monitoring_visit(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/monitoring-visits", payload, headers)

    def list_work_order_monitoring_visits(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/monitoring-visits", headers=headers, params=params)

    def get_monitoring_visit(self, visit_id, headers):
        return self._request("GET", f"/monitoring-visits/{visit_id}", headers=headers)

    def list_monitoring_visits(self, headers, params=None):
        return self._request("GET", "/monitoring-visits", headers=headers, params=params)

    # ---- WarrantyClaim ----
    def create_warranty_claim(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/warranty-claims", payload, headers)

    def list_work_order_warranty_claims(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def adjudicate_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/warranty-claims/{claim_id}/adjudicate", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
