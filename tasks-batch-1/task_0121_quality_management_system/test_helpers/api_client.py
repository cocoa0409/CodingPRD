"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Personnel ----
    def create_personnel(self, payload, headers):
        return self._request("POST", "/personnel", payload, headers)

    def get_personnel(self, personnel_id, headers):
        return self._request("GET", f"/personnel/{personnel_id}", headers=headers)

    # ---- Supplier ----
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def list_supplier_scars(self, supplier_id, headers, params=None):
        return self._request("GET", f"/suppliers/{supplier_id}/scars", headers=headers, params=params)

    def list_supplier_inspection_lots(self, supplier_id, headers, params=None):
        return self._request("GET", f"/suppliers/{supplier_id}/inspection-lots", headers=headers, params=params)

    def list_supplier_deviations(self, supplier_id, headers, params=None):
        return self._request("GET", f"/suppliers/{supplier_id}/deviations", headers=headers, params=params)

    # ---- NonconformanceReport ----
    def create_ncr(self, payload, headers):
        return self._request("POST", "/nonconformance-reports", payload, headers)

    def get_ncr(self, ncr_id, headers):
        return self._request("GET", f"/nonconformance-reports/{ncr_id}", headers=headers)

    def list_ncrs(self, headers, params=None):
        return self._request("GET", "/nonconformance-reports", headers=headers, params=params)

    def open_ncr(self, ncr_id, headers):
        return self._request("POST", f"/nonconformance-reports/{ncr_id}/open", {}, headers)

    def disposition_ncr(self, ncr_id, payload, headers):
        return self._request("POST", f"/nonconformance-reports/{ncr_id}/disposition", payload, headers)

    def void_ncr(self, ncr_id, headers):
        return self._request("POST", f"/nonconformance-reports/{ncr_id}/void", {}, headers)

    def list_ncr_capas(self, ncr_id, headers, params=None):
        return self._request("GET", f"/nonconformance-reports/{ncr_id}/capas", headers=headers, params=params)

    def list_ncr_scars(self, ncr_id, headers, params=None):
        return self._request("GET", f"/nonconformance-reports/{ncr_id}/scars", headers=headers, params=params)

    def list_ncr_deviations(self, ncr_id, headers, params=None):
        return self._request("GET", f"/nonconformance-reports/{ncr_id}/deviations", headers=headers, params=params)

    # ---- Capa ----
    def create_capa(self, payload, headers):
        return self._request("POST", "/capas", payload, headers)

    def get_capa(self, capa_id, headers):
        return self._request("GET", f"/capas/{capa_id}", headers=headers)

    def create_capa_step(self, capa_id, payload, headers):
        return self._request("POST", f"/capas/{capa_id}/steps", payload, headers)

    def list_capa_steps(self, capa_id, headers, params=None):
        return self._request("GET", f"/capas/{capa_id}/steps", headers=headers, params=params)

    def transition_capa(self, capa_id, payload, headers):
        return self._request("POST", f"/capas/{capa_id}/transition", payload, headers)

    # ---- Scar ----
    def create_scar(self, payload, headers):
        return self._request("POST", "/scars", payload, headers)

    def get_scar(self, scar_id, headers):
        return self._request("GET", f"/scars/{scar_id}", headers=headers)

    def transition_scar(self, scar_id, payload, headers):
        return self._request("POST", f"/scars/{scar_id}/transition", payload, headers)

    # ---- ControlPlan / ControlPlanRevision ----
    def create_control_plan(self, payload, headers):
        return self._request("POST", "/control-plans", payload, headers)

    def get_control_plan(self, control_plan_id, headers):
        return self._request("GET", f"/control-plans/{control_plan_id}", headers=headers)

    def create_control_plan_revision(self, payload, headers):
        return self._request("POST", "/control-plan-revisions", payload, headers)

    def list_control_plan_revisions(self, control_plan_id, headers, params=None):
        return self._request("GET", f"/control-plans/{control_plan_id}/revisions", headers=headers, params=params)

    def approve_control_plan_revision(self, revision_id, headers):
        return self._request("POST", f"/control-plan-revisions/{revision_id}/approve", {}, headers)

    def list_control_plan_inspection_plans(self, control_plan_id, headers, params=None):
        return self._request("GET", f"/control-plans/{control_plan_id}/inspection-plans", headers=headers, params=params)

    # ---- InspectionPlan / InspectionLot ----
    def create_inspection_plan(self, payload, headers):
        return self._request("POST", "/inspection-plans", payload, headers)

    def get_inspection_plan(self, inspection_plan_id, headers):
        return self._request("GET", f"/inspection-plans/{inspection_plan_id}", headers=headers)

    def create_inspection_lot(self, payload, headers):
        return self._request("POST", "/inspection-lots", payload, headers)

    def get_inspection_lot(self, inspection_lot_id, headers):
        return self._request("GET", f"/inspection-lots/{inspection_lot_id}", headers=headers)

    def list_inspection_plan_lots(self, inspection_plan_id, headers, params=None):
        return self._request("GET", f"/inspection-plans/{inspection_plan_id}/inspection-lots", headers=headers, params=params)

    def transition_inspection_lot(self, inspection_lot_id, payload, headers):
        return self._request("POST", f"/inspection-lots/{inspection_lot_id}/transition", payload, headers)

    # ---- Audit / AuditFinding ----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def transition_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/transition", payload, headers)

    def create_audit_finding(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/findings", payload, headers)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"/audit-findings/{finding_id}", headers=headers)

    def list_audit_findings(self, audit_id, headers, params=None):
        return self._request("GET", f"/audits/{audit_id}/findings", headers=headers, params=params)

    def transition_audit_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/audit-findings/{finding_id}/transition", payload, headers)

    # ---- Deviation ----
    def create_deviation(self, payload, headers):
        return self._request("POST", "/deviations", payload, headers)

    def get_deviation(self, deviation_id, headers):
        return self._request("GET", f"/deviations/{deviation_id}", headers=headers)

    def transition_deviation(self, deviation_id, payload, headers):
        return self._request("POST", f"/deviations/{deviation_id}/transition", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
