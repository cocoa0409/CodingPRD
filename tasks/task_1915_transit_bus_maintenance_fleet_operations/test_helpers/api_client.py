"""API client: one method per endpoint defined in the PRD (all under /fleet)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock & ops epoch ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/fleet/_clock/set_current_utc", payload, headers)

    def run_epoch(self, headers):
        return self._request("POST", "/fleet/run_epoch", {}, headers)

    # --- buses ---
    def create_bus(self, payload, headers):
        return self._request("POST", "/fleet/buses", payload, headers)

    def get_bus(self, bus_id, headers):
        return self._request("GET", f"/fleet/buses/{bus_id}", headers=headers)

    def list_buses(self, headers, params=None):
        return self._request("GET", "/fleet/buses", headers=headers, params=params)

    def get_bus_pm_status(self, bus_id, headers, params=None):
        return self._request(
            "GET", f"/fleet/buses/{bus_id}/pm-status", headers=headers, params=params
        )

    def retire_bus(self, bus_id, payload, headers):
        return self._request("POST", f"/fleet/buses/{bus_id}/retire", payload, headers)

    def list_bus_work_orders(self, bus_id, headers):
        return self._request("GET", f"/fleet/buses/{bus_id}/work-orders", headers=headers)

    def list_bus_warranty_claims(self, bus_id, headers):
        return self._request(
            "GET", f"/fleet/buses/{bus_id}/warranty-claims", headers=headers
        )

    def list_bus_defect_reports(self, bus_id, headers):
        return self._request(
            "GET", f"/fleet/buses/{bus_id}/defect-reports", headers=headers
        )

    def list_bus_mileage_fuel_logs(self, bus_id, headers):
        return self._request(
            "GET", f"/fleet/buses/{bus_id}/mileage-fuel-logs", headers=headers
        )

    def list_bus_emissions_inspections(self, bus_id, headers):
        return self._request(
            "GET", f"/fleet/buses/{bus_id}/emissions-inspections", headers=headers
        )

    # --- PM policies ---
    def create_pm_policy(self, payload, headers):
        return self._request("POST", "/fleet/pm-policies", payload, headers)

    def get_pm_policy(self, policy_id, headers):
        return self._request("GET", f"/fleet/pm-policies/{policy_id}", headers=headers)

    def list_pm_policies(self, headers, params=None):
        return self._request("GET", "/fleet/pm-policies", headers=headers, params=params)

    # --- mileage & fuel logs ---
    def create_mileage_fuel_log(self, payload, headers):
        return self._request("POST", "/fleet/mileage-fuel-logs", payload, headers)

    def get_mileage_fuel_log(self, log_id, headers):
        return self._request(
            "GET", f"/fleet/mileage-fuel-logs/{log_id}", headers=headers
        )

    def list_mileage_fuel_logs(self, headers, params=None):
        return self._request(
            "GET", "/fleet/mileage-fuel-logs", headers=headers, params=params
        )

    def list_log_defect_reports(self, log_id, headers):
        return self._request(
            "GET", f"/fleet/mileage-fuel-logs/{log_id}/defect-reports", headers=headers
        )

    def void_mileage_fuel_log(self, log_id, payload, headers):
        return self._request(
            "POST", f"/fleet/mileage-fuel-logs/{log_id}/void", payload, headers
        )

    # --- work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/fleet/work-orders", payload, headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/fleet/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/fleet/work-orders", headers=headers, params=params)

    def work_order_event(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/fleet/work-orders/{wo_id}/events", payload, headers
        )

    def add_labor_entry(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/fleet/work-orders/{wo_id}/labor-entries", payload, headers
        )

    def list_wo_part_lines(self, wo_id, headers):
        return self._request(
            "GET", f"/fleet/work-orders/{wo_id}/part-lines", headers=headers
        )

    def list_wo_warranty_claims(self, wo_id, headers):
        return self._request(
            "GET", f"/fleet/work-orders/{wo_id}/warranty-claims", headers=headers
        )

    def list_wo_defect_reports(self, wo_id, headers):
        return self._request(
            "GET", f"/fleet/work-orders/{wo_id}/defect-reports", headers=headers
        )

    # --- part lines ---
    def create_part_line(self, wo_id, payload, headers):
        return self._request(
            "POST", f"/fleet/work-orders/{wo_id}/part-lines", payload, headers
        )

    def get_part_line(self, line_id, headers):
        return self._request("GET", f"/fleet/part-lines/{line_id}", headers=headers)

    def list_part_lines(self, headers, params=None):
        return self._request("GET", "/fleet/part-lines", headers=headers, params=params)

    def part_line_event(self, line_id, payload, headers):
        return self._request(
            "POST", f"/fleet/part-lines/{line_id}/events", payload, headers
        )

    # --- parts ---
    def create_part(self, payload, headers):
        return self._request("POST", "/fleet/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/fleet/parts/{part_id}", headers=headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/fleet/parts", headers=headers, params=params)

    def create_stock_adjustment(self, part_id, payload, headers):
        return self._request(
            "POST", f"/fleet/parts/{part_id}/stock-adjustments", payload, headers
        )

    def supersede_part(self, part_id, payload, headers):
        return self._request("POST", f"/fleet/parts/{part_id}/supersede", payload, headers)

    def list_part_emissions_inspections(self, part_id, headers):
        return self._request(
            "GET", f"/fleet/parts/{part_id}/emissions-inspections", headers=headers
        )

    def list_part_campaigns(self, part_id, headers):
        return self._request("GET", f"/fleet/parts/{part_id}/campaigns", headers=headers)

    # --- defect reports & road calls ---
    def create_defect_report(self, payload, headers):
        return self._request("POST", "/fleet/defect-reports", payload, headers)

    def get_defect_report(self, defect_id, headers):
        return self._request("GET", f"/fleet/defect-reports/{defect_id}", headers=headers)

    def list_defect_reports(self, headers, params=None):
        return self._request(
            "GET", "/fleet/defect-reports", headers=headers, params=params
        )

    def defect_event(self, defect_id, payload, headers):
        return self._request(
            "POST", f"/fleet/defect-reports/{defect_id}/events", payload, headers
        )

    def list_defect_work_orders(self, defect_id, headers):
        return self._request(
            "GET", f"/fleet/defect-reports/{defect_id}/work-orders", headers=headers
        )

    # --- campaigns ---
    def create_campaign(self, payload, headers):
        return self._request("POST", "/fleet/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/fleet/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/fleet/campaigns", headers=headers, params=params)

    def campaign_event(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/fleet/campaigns/{campaign_id}/events", payload, headers
        )

    def list_campaign_work_orders(self, campaign_id, headers):
        return self._request(
            "GET", f"/fleet/campaigns/{campaign_id}/work-orders", headers=headers
        )

    # --- emissions inspections ---
    def create_emissions_inspection(self, payload, headers):
        return self._request("POST", "/fleet/emissions-inspections", payload, headers)

    def get_emissions_inspection(self, inspection_id, headers):
        return self._request(
            "GET", f"/fleet/emissions-inspections/{inspection_id}", headers=headers
        )

    def list_emissions_inspections(self, headers, params=None):
        return self._request(
            "GET", "/fleet/emissions-inspections", headers=headers, params=params
        )

    def list_inspection_work_orders(self, inspection_id, headers):
        return self._request(
            "GET",
            f"/fleet/emissions-inspections/{inspection_id}/work-orders",
            headers=headers,
        )

    # --- warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/fleet/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/fleet/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/fleet/warranty-claims", headers=headers, params=params
        )

    def warranty_claim_event(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/fleet/warranty-claims/{claim_id}/events", payload, headers
        )

    # --- shifts & coverage ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/fleet/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/fleet/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/fleet/shifts", headers=headers, params=params)

    def publish_shift(self, shift_id, headers):
        return self._request("POST", f"/fleet/shifts/{shift_id}/publish", {}, headers)

    def reconcile_shift(self, shift_id, headers):
        return self._request("POST", f"/fleet/shifts/{shift_id}/reconcile", {}, headers)

    def create_shift_assignment(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/fleet/shifts/{shift_id}/assignments", payload, headers
        )

    def list_shift_assignments(self, shift_id, headers):
        return self._request(
            "GET", f"/fleet/shifts/{shift_id}/assignments", headers=headers
        )

    def shift_assignment_event(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/fleet/shift-assignments/{assignment_id}/events", payload, headers
        )

    # --- mechanics & certifications ---
    def create_mechanic(self, payload, headers):
        return self._request("POST", "/fleet/mechanics", payload, headers)

    def get_mechanic(self, mechanic_id, headers):
        return self._request("GET", f"/fleet/mechanics/{mechanic_id}", headers=headers)

    def list_mechanics(self, headers, params=None):
        return self._request("GET", "/fleet/mechanics", headers=headers, params=params)

    def list_mechanic_shift_assignments(self, mechanic_id, headers):
        return self._request(
            "GET", f"/fleet/mechanics/{mechanic_id}/shift-assignments", headers=headers
        )

    def list_mechanic_work_orders(self, mechanic_id, headers):
        return self._request(
            "GET", f"/fleet/mechanics/{mechanic_id}/work-orders", headers=headers
        )

    def list_mechanic_defect_reports(self, mechanic_id, headers):
        return self._request(
            "GET", f"/fleet/mechanics/{mechanic_id}/defect-reports", headers=headers
        )

    def create_certification(self, mechanic_id, payload, headers):
        return self._request(
            "POST", f"/fleet/mechanics/{mechanic_id}/certifications", payload, headers
        )

    def list_mechanic_certifications(self, mechanic_id, headers):
        return self._request(
            "GET", f"/fleet/mechanics/{mechanic_id}/certifications", headers=headers
        )

    def get_certification(self, cert_id, headers):
        return self._request("GET", f"/fleet/certifications/{cert_id}", headers=headers)

    def renew_certification(self, cert_id, payload, headers):
        return self._request(
            "POST", f"/fleet/certifications/{cert_id}/renew", payload, headers
        )

    # --- fleet replacement planning ---
    def create_replacement_plan(self, payload, headers):
        return self._request("POST", "/fleet/replacement-plans", payload, headers)

    def get_replacement_plan(self, plan_id, headers):
        return self._request("GET", f"/fleet/replacement-plans/{plan_id}", headers=headers)

    def replacement_plan_event(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/fleet/replacement-plans/{plan_id}/events", payload, headers
        )

    # --- fleet posture (computed read) ---
    def get_posture(self, headers):
        return self._request("GET", "/fleet/posture", headers=headers)


api_client = ApiClient()
