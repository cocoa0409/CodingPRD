"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)

    # ---- Asset ----
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers=headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def retire_asset(self, asset_id, headers):
        return self._request("POST", f"/assets/{asset_id}/retire", headers=headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers=headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def submit_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/submit", headers=headers)

    def decide_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/decision", payload, headers=headers)

    # ---- ServiceRequest ----
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers=headers)

    def get_service_request(self, sr_id, headers):
        return self._request("GET", f"/service-requests/{sr_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def triage_service_request(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/triage", payload, headers=headers)

    # ---- WorkOrder ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers=headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def schedule_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/work-orders/{wo_id}/schedule", payload, headers=headers)

    def dispatch_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/dispatch", headers=headers)

    def start_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/start", headers=headers)

    def hold_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/hold", headers=headers)

    def resume_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/resume", headers=headers)

    def complete_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/complete", headers=headers)

    def cancel_work_order(self, wo_id, headers):
        return self._request("POST", f"/work-orders/{wo_id}/cancel", headers=headers)

    # ---- Crew ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers=headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crews(self, headers, params=None):
        return self._request("GET", "/crews", headers=headers, params=params)

    # ---- Dispatch ----
    def create_dispatch(self, payload, headers):
        return self._request("POST", "/dispatches", payload, headers=headers)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dispatches", headers=headers, params=params)

    def cancel_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/dispatches/{dispatch_id}/cancel", headers=headers)

    # ---- Yard ----
    def create_yard(self, payload, headers):
        return self._request("POST", "/yards", payload, headers=headers)

    def get_yard(self, yard_id, headers):
        return self._request("GET", f"/yards/{yard_id}", headers=headers)

    def list_yards(self, headers, params=None):
        return self._request("GET", "/yards", headers=headers, params=params)

    # ---- MaterialItem ----
    def create_material_item(self, payload, headers):
        return self._request("POST", "/material-items", payload, headers=headers)

    def get_material_item(self, item_id, headers):
        return self._request("GET", f"/material-items/{item_id}", headers=headers)

    def list_material_items(self, headers, params=None):
        return self._request("GET", "/material-items", headers=headers, params=params)

    def restock_material_item(self, item_id, payload, headers):
        return self._request("POST", f"/material-items/{item_id}/restock", payload, headers=headers)

    # ---- MaterialReservation ----
    def create_material_reservation(self, payload, headers):
        return self._request("POST", "/material-reservations", payload, headers=headers)

    def get_material_reservation(self, res_id, headers):
        return self._request("GET", f"/material-reservations/{res_id}", headers=headers)

    def list_material_reservations(self, headers, params=None):
        return self._request("GET", "/material-reservations", headers=headers, params=params)

    def release_material_reservation(self, res_id, headers):
        return self._request("POST", f"/material-reservations/{res_id}/release", headers=headers)

    # ---- ROWPermit ----
    def create_row_permit(self, payload, headers):
        return self._request("POST", "/row-permits", payload, headers=headers)

    def get_row_permit(self, permit_id, headers):
        return self._request("GET", f"/row-permits/{permit_id}", headers=headers)

    def list_row_permits(self, headers, params=None):
        return self._request("GET", "/row-permits", headers=headers, params=params)

    def decide_row_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/row-permits/{permit_id}/decision", payload, headers=headers)

    def release_row_permit(self, permit_id, headers):
        return self._request("POST", f"/row-permits/{permit_id}/release", headers=headers)


api_client = ApiClient()
