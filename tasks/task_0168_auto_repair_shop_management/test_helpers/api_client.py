"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_vehicles(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/vehicles", headers=headers, params=params)

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    # --- Technician ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # --- ServiceBay ---
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/service-bays", payload, headers)

    # --- LaborOperation ---
    def create_labor_operation(self, payload, headers):
        return self._request("POST", "/labor-operations", payload, headers)

    # --- MarkupTier ---
    def create_markup_tier(self, payload, headers):
        return self._request("POST", "/markup-tiers", payload, headers)

    def list_markup_tiers(self, headers, params=None):
        return self._request("GET", "/markup-tiers", headers=headers, params=params)

    # --- RepairOrder ---
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/repair-orders", payload, headers)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/repair-orders/{ro_id}", headers=headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/repair-orders", headers=headers, params=params)

    def schedule_repair_order(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/schedule", payload, headers)

    def authorize_repair_order(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/authorize", payload, headers)

    def transition_repair_order(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/transition", payload, headers)

    def complete_repair_order(self, ro_id, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/complete", {}, headers)

    # --- LaborLine ---
    def create_labor_line(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/labor-lines", payload, headers)

    def list_repair_order_labor_lines(self, ro_id, headers, params=None):
        return self._request("GET", f"/repair-orders/{ro_id}/labor-lines", headers=headers, params=params)

    def get_labor_line(self, ll_id, headers):
        return self._request("GET", f"/labor-lines/{ll_id}", headers=headers)

    def list_labor_lines(self, headers, params=None):
        return self._request("GET", "/labor-lines", headers=headers, params=params)

    def clock_in_labor_line(self, ll_id, payload, headers):
        return self._request("POST", f"/labor-lines/{ll_id}/clock-in", payload, headers)

    def clock_out_labor_line(self, ll_id, payload, headers):
        return self._request("POST", f"/labor-lines/{ll_id}/clock-out", payload, headers)

    def complete_labor_line(self, ll_id, headers):
        return self._request("POST", f"/labor-lines/{ll_id}/complete", {}, headers)

    # --- PartLine ---
    def create_part_line(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/part-lines", payload, headers)

    def list_repair_order_part_lines(self, ro_id, headers, params=None):
        return self._request("GET", f"/repair-orders/{ro_id}/part-lines", headers=headers, params=params)

    def get_part_line(self, pl_id, headers):
        return self._request("GET", f"/part-lines/{pl_id}", headers=headers)

    def install_part_line(self, pl_id, headers):
        return self._request("POST", f"/part-lines/{pl_id}/install", {}, headers)

    # --- CoreCharge ---
    def list_repair_order_core_charges(self, ro_id, headers, params=None):
        return self._request("GET", f"/repair-orders/{ro_id}/core-charges", headers=headers, params=params)

    def get_core_charge(self, cc_id, headers):
        return self._request("GET", f"/core-charges/{cc_id}", headers=headers)

    def list_core_charges(self, headers, params=None):
        return self._request("GET", "/core-charges", headers=headers, params=params)

    def return_core_charge(self, cc_id, headers):
        return self._request("POST", f"/core-charges/{cc_id}/return", {}, headers)

    def forfeit_core_charge(self, cc_id, headers):
        return self._request("POST", f"/core-charges/{cc_id}/forfeit", {}, headers)

    # --- Inspection ---
    def create_inspection(self, ro_id, payload, headers):
        return self._request("POST", f"/repair-orders/{ro_id}/inspections", payload, headers)

    def list_repair_order_inspections(self, ro_id, headers, params=None):
        return self._request("GET", f"/repair-orders/{ro_id}/inspections", headers=headers, params=params)

    def get_inspection(self, insp_id, headers):
        return self._request("GET", f"/inspections/{insp_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def add_inspection_item(self, insp_id, payload, headers):
        return self._request("POST", f"/inspections/{insp_id}/items", payload, headers)

    def submit_inspection(self, insp_id, headers):
        return self._request("POST", f"/inspections/{insp_id}/submit", {}, headers)

    def review_inspection(self, insp_id, headers):
        return self._request("POST", f"/inspections/{insp_id}/review", {}, headers)

    # --- RecommendedJob ---
    def create_recommended_job(self, insp_id, payload, headers):
        return self._request("POST", f"/inspections/{insp_id}/recommended-jobs", payload, headers)

    def list_inspection_recommended_jobs(self, insp_id, headers, params=None):
        return self._request("GET", f"/inspections/{insp_id}/recommended-jobs", headers=headers, params=params)

    def get_recommended_job(self, rj_id, headers):
        return self._request("GET", f"/recommended-jobs/{rj_id}", headers=headers)

    def list_recommended_jobs(self, headers, params=None):
        return self._request("GET", "/recommended-jobs", headers=headers, params=params)

    def decide_recommended_job(self, rj_id, payload, headers):
        return self._request("POST", f"/recommended-jobs/{rj_id}/decision", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
