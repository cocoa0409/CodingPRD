"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/pm/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/pm/properties/{property_id}", headers=headers)

    def archive_property(self, property_id, headers):
        return self._request("POST", f"/pm/properties/{property_id}/archive", {}, headers)

    # --- Buildings ---
    def create_building(self, payload, headers):
        return self._request("POST", "/pm/buildings", payload, headers)

    def get_building(self, building_id, headers):
        return self._request("GET", f"/pm/buildings/{building_id}", headers=headers)

    def list_buildings(self, property_id, headers, params=None):
        return self._request("GET", f"/pm/properties/{property_id}/buildings", headers=headers, params=params)

    # --- Units ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/pm/units", payload, headers)

    def list_units(self, building_id, headers, params=None):
        return self._request("GET", f"/pm/buildings/{building_id}/units", headers=headers, params=params)

    # --- Assets ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/pm/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/pm/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/pm/assets", headers=headers, params=params)

    def set_asset_operational_status(self, asset_id, payload, headers):
        return self._request("POST", f"/pm/assets/{asset_id}/operational-status", payload, headers)

    def decommission_asset(self, asset_id, headers):
        return self._request("POST", f"/pm/assets/{asset_id}/decommission", {}, headers)

    # --- PM task templates ---
    def create_template(self, payload, headers):
        return self._request("POST", "/pm/pm-task-templates", payload, headers)

    def list_templates(self, property_id, headers, params=None):
        return self._request("GET", f"/pm/properties/{property_id}/pm-task-templates", headers=headers, params=params)

    def retire_template(self, template_id, headers):
        return self._request("POST", f"/pm/pm-task-templates/{template_id}/retire", {}, headers)

    # --- Plans & ledger ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/pm/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/pm/plans/{plan_id}", headers=headers)

    def list_plans(self, property_id, headers, params=None):
        return self._request("GET", f"/pm/properties/{property_id}/plans", headers=headers, params=params)

    def adopt_plan(self, plan_id, headers):
        return self._request("POST", f"/pm/plans/{plan_id}/adopt", {}, headers)

    def close_plan(self, plan_id, headers):
        return self._request("POST", f"/pm/plans/{plan_id}/close", {}, headers)

    def list_plan_ledger(self, plan_id, headers, params=None):
        return self._request("GET", f"/pm/plans/{plan_id}/ledger", headers=headers, params=params)

    # --- Entry batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/pm/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/pm/batches/{batch_id}", headers=headers)

    def list_batches(self, property_id, headers, params=None):
        return self._request("GET", f"/pm/properties/{property_id}/batches", headers=headers, params=params)

    def publish_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/pm/batches/{batch_id}/publish", payload, headers)

    def lock_batch(self, batch_id, headers):
        return self._request("POST", f"/pm/batches/{batch_id}/lock", {}, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/pm/batches/{batch_id}/cancel", {}, headers)

    # --- Visits ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/pm/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/pm/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/pm/visits", headers=headers, params=params)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/start", {}, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/complete", payload, headers)

    def no_access_visit(self, visit_id, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/no-access", {}, headers)

    def reschedule_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/reschedule", payload, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/cancel", {}, headers)

    # --- Evidence / deficiencies / audit ---
    def create_evidence(self, visit_id, payload, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/evidence", payload, headers)

    def list_evidence(self, visit_id, headers):
        return self._request("GET", f"/pm/visits/{visit_id}/evidence", headers=headers)

    def create_deficiency(self, visit_id, payload, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/deficiencies", payload, headers)

    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/pm/deficiencies", headers=headers, params=params)

    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/pm/deficiencies/{deficiency_id}", headers=headers)

    def triage_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"/pm/deficiencies/{deficiency_id}/triage", {}, headers)

    def waive_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"/pm/deficiencies/{deficiency_id}/waive", {}, headers)

    def create_audit(self, visit_id, payload, headers):
        return self._request("POST", f"/pm/visits/{visit_id}/audit", payload, headers)

    def get_audit(self, visit_id, headers):
        return self._request("GET", f"/pm/visits/{visit_id}/audit", headers=headers)

    # --- Corrective work orders ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/pm/work-orders", payload, headers)

    def get_work_order(self, wo_id, headers):
        return self._request("GET", f"/pm/work-orders/{wo_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/pm/work-orders", headers=headers, params=params)

    def submit_work_order_review(self, wo_id, headers):
        return self._request("POST", f"/pm/work-orders/{wo_id}/submit-review", {}, headers)

    def approve_work_order(self, wo_id, headers):
        return self._request("POST", f"/pm/work-orders/{wo_id}/approve", {}, headers)

    def return_work_order_rework(self, wo_id, headers):
        return self._request("POST", f"/pm/work-orders/{wo_id}/return-rework", {}, headers)

    def reject_work_order(self, wo_id, headers):
        return self._request("POST", f"/pm/work-orders/{wo_id}/reject", {}, headers)

    def start_work_order(self, wo_id, headers):
        return self._request("POST", f"/pm/work-orders/{wo_id}/start", {}, headers)

    def complete_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/pm/work-orders/{wo_id}/complete", payload, headers)

    def verify_work_order(self, wo_id, payload, headers):
        return self._request("POST", f"/pm/work-orders/{wo_id}/verify", payload, headers)

    # --- Ledger reverse reachability ---
    def list_visit_ledger_entries(self, visit_id, headers):
        return self._request("GET", f"/pm/visits/{visit_id}/ledger-entries", headers=headers)

    def list_wo_ledger_entries(self, wo_id, headers):
        return self._request("GET", f"/pm/work-orders/{wo_id}/ledger-entries", headers=headers)

    # --- Forecasting & compliance read ---
    def create_capital_forecast(self, payload, headers):
        return self._request("POST", "/pm/capital-forecasts", payload, headers)

    def list_capital_forecasts(self, property_id, headers, params=None):
        return self._request("GET", f"/pm/properties/{property_id}/capital-forecasts", headers=headers, params=params)

    def get_compliance_summary(self, headers, params=None):
        return self._request("GET", "/pm/compliance-summary", headers=headers, params=params)


api_client = ApiClient()
