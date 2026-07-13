"""API client: one method per endpoint defined in the PRD (mounted under /forestry)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Zones ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/forestry/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/forestry/zones/{zone_id}", headers=headers)

    # ---- Species ----
    def create_species(self, payload, headers):
        return self._request("POST", "/forestry/species", payload, headers)

    def get_species(self, species_id, headers):
        return self._request("GET", f"/forestry/species/{species_id}", headers=headers)

    # ---- Trees ----
    def create_tree(self, payload, headers):
        return self._request("POST", "/forestry/trees", payload, headers)

    def get_tree(self, tree_id, headers):
        return self._request("GET", f"/forestry/trees/{tree_id}", headers=headers)

    def list_trees(self, headers, params=None):
        return self._request("GET", "/forestry/trees", headers=headers, params=params)

    def create_inspection(self, tree_id, payload, headers):
        return self._request("POST", f"/forestry/trees/{tree_id}/inspections", payload, headers)

    def list_tree_inspections(self, tree_id, headers, params=None):
        return self._request("GET", f"/forestry/trees/{tree_id}/inspections", headers=headers, params=params)

    # ---- Inspections ----
    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/forestry/inspections/{inspection_id}", headers=headers)

    def finalize_inspection(self, inspection_id, headers):
        return self._request("POST", f"/forestry/inspections/{inspection_id}/finalize", {}, headers)

    def dispute_inspection(self, inspection_id, headers):
        return self._request("POST", f"/forestry/inspections/{inspection_id}/dispute", {}, headers)

    # ---- Permits ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/forestry/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/forestry/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/forestry/permits", headers=headers, params=params)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/forestry/permits/{permit_id}/submit", {}, headers)

    def review_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/forestry/permits/{permit_id}/review", payload, headers)

    def provide_info(self, permit_id, payload, headers):
        return self._request("POST", f"/forestry/permits/{permit_id}/provide-info", payload, headers)

    def pay_fee(self, permit_id, payload, headers):
        return self._request("POST", f"/forestry/permits/{permit_id}/pay-fee", payload, headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/forestry/permits/{permit_id}/issue", {}, headers)

    def revoke_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/forestry/permits/{permit_id}/revoke", payload, headers)

    def list_permit_plantings(self, permit_id, headers, params=None):
        return self._request("GET", f"/forestry/permits/{permit_id}/replacement-plantings",
                             headers=headers, params=params)

    # ---- Replacement plantings ----
    def get_replacement_planting(self, planting_id, headers):
        return self._request("GET", f"/forestry/replacement-plantings/{planting_id}", headers=headers)

    def list_replacement_plantings(self, headers, params=None):
        return self._request("GET", "/forestry/replacement-plantings", headers=headers, params=params)

    def plant_replacement(self, planting_id, headers):
        return self._request("POST", f"/forestry/replacement-plantings/{planting_id}/plant", {}, headers)

    def establish_replacement(self, planting_id, headers):
        return self._request("POST", f"/forestry/replacement-plantings/{planting_id}/establish", {}, headers)

    # ---- Contractors ----
    def create_contractor(self, payload, headers):
        return self._request("POST", "/forestry/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/forestry/contractors/{contractor_id}", headers=headers)

    # ---- Work orders ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/forestry/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/forestry/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/forestry/work-orders", headers=headers, params=params)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/forestry/work-orders/{work_order_id}/start", {}, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/forestry/work-orders/{work_order_id}/complete", {}, headers)

    def abort_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/forestry/work-orders/{work_order_id}/abort", payload, headers)

    # ---- 811 dig tickets ----
    def create_dig_ticket(self, work_order_id, payload, headers):
        return self._request("POST", f"/forestry/work-orders/{work_order_id}/dig-tickets", payload, headers)

    def list_dig_tickets(self, work_order_id, headers, params=None):
        return self._request("GET", f"/forestry/work-orders/{work_order_id}/dig-tickets",
                             headers=headers, params=params)

    def get_dig_ticket(self, dig_ticket_id, headers):
        return self._request("GET", f"/forestry/dig-tickets/{dig_ticket_id}", headers=headers)

    def mark_valid_dig_ticket(self, dig_ticket_id, headers):
        return self._request("POST", f"/forestry/dig-tickets/{dig_ticket_id}/mark-valid", {}, headers)

    # ---- Storm events ----
    def create_storm_event(self, payload, headers):
        return self._request("POST", "/forestry/storm-events", payload, headers)

    def get_storm_event(self, storm_event_id, headers):
        return self._request("GET", f"/forestry/storm-events/{storm_event_id}", headers=headers)

    def list_storm_events(self, headers, params=None):
        return self._request("GET", "/forestry/storm-events", headers=headers, params=params)

    def close_storm_event(self, storm_event_id, headers):
        return self._request("POST", f"/forestry/storm-events/{storm_event_id}/close", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/forestry/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
