"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/qa/_clock/set_current_utc", payload, headers)

    # --- allergens ---
    def create_allergen(self, payload, headers):
        return self._request("POST", "/qa/allergens", payload, headers)

    def list_allergens(self, headers, params=None):
        return self._request("GET", "/qa/allergens", headers=headers, params=params)

    def get_allergen(self, allergen_id, headers):
        return self._request("GET", f"/qa/allergens/{allergen_id}", headers=headers)

    # --- production lines ---
    def create_production_line(self, payload, headers):
        return self._request("POST", "/qa/production-lines", payload, headers)

    def list_production_lines(self, headers, params=None):
        return self._request("GET", "/qa/production-lines", headers=headers, params=params)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/qa/production-lines/{line_id}", headers=headers)

    # --- line-allergen matrix entries ---
    def create_matrix_entry(self, payload, headers):
        return self._request("POST", "/qa/line-allergen-matrix-entries", payload, headers)

    def list_matrix_entries(self, headers, params=None):
        return self._request("GET", "/qa/line-allergen-matrix-entries", headers=headers, params=params)

    def get_matrix_entry(self, entry_id, headers):
        return self._request("GET", f"/qa/line-allergen-matrix-entries/{entry_id}", headers=headers)

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/qa/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/qa/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/qa/products/{product_id}", headers=headers)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/qa/products/{product_id}", payload, headers)

    def supplier_allergen_change(self, product_id, payload, headers):
        return self._request("POST", f"/qa/products/{product_id}/supplier-allergen-change", payload, headers)

    # --- production runs ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/qa/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/qa/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/qa/production-runs/{run_id}", headers=headers)

    def schedule_run(self, run_id, payload, headers):
        return self._request("POST", f"/qa/production-runs/{run_id}/schedule", payload, headers)

    def unschedule_run(self, run_id, headers):
        return self._request("POST", f"/qa/production-runs/{run_id}/unschedule", {}, headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/qa/production-runs/{run_id}/start", {}, headers)

    def complete_run(self, run_id, headers):
        return self._request("POST", f"/qa/production-runs/{run_id}/complete", {}, headers)

    def reject_run(self, run_id, headers):
        return self._request("POST", f"/qa/production-runs/{run_id}/reject", {}, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/qa/production-runs/{run_id}/cancel", {}, headers)

    # --- changeover procedures ---
    def create_changeover_procedure(self, payload, headers):
        return self._request("POST", "/qa/changeover-procedures", payload, headers)

    def list_changeover_procedures(self, headers, params=None):
        return self._request("GET", "/qa/changeover-procedures", headers=headers, params=params)

    def get_changeover_procedure(self, procedure_id, headers):
        return self._request("GET", f"/qa/changeover-procedures/{procedure_id}", headers=headers)

    def approve_procedure(self, procedure_id, payload, headers):
        return self._request("POST", f"/qa/changeover-procedures/{procedure_id}/approve", payload, headers)

    def retire_procedure(self, procedure_id, headers):
        return self._request("POST", f"/qa/changeover-procedures/{procedure_id}/retire", {}, headers)

    # --- changeovers ---
    def create_changeover(self, payload, headers):
        return self._request("POST", "/qa/changeovers", payload, headers)

    def list_changeovers(self, headers, params=None):
        return self._request("GET", "/qa/changeovers", headers=headers, params=params)

    def get_changeover(self, changeover_id, headers):
        return self._request("GET", f"/qa/changeovers/{changeover_id}", headers=headers)

    def begin_changeover(self, changeover_id, headers):
        return self._request("POST", f"/qa/changeovers/{changeover_id}/begin", {}, headers)

    def finish_changeover_execution(self, changeover_id, payload, headers):
        return self._request("POST", f"/qa/changeovers/{changeover_id}/finish-execution", payload, headers)

    def reswab_changeover(self, changeover_id, headers):
        return self._request("POST", f"/qa/changeovers/{changeover_id}/reswab", {}, headers)

    def cancel_changeover(self, changeover_id, headers):
        return self._request("POST", f"/qa/changeovers/{changeover_id}/cancel", {}, headers)

    # --- swab results ---
    def record_swab_result(self, changeover_id, payload, headers):
        return self._request("POST", f"/qa/changeovers/{changeover_id}/swab-results", payload, headers)

    def list_swab_results(self, headers, params=None):
        return self._request("GET", "/qa/swab-results", headers=headers, params=params)

    def get_swab_result(self, swab_id, headers):
        return self._request("GET", f"/qa/swab-results/{swab_id}", headers=headers)

    # --- technicians ---
    def create_technician(self, payload, headers):
        return self._request("POST", "/qa/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/qa/technicians", headers=headers, params=params)

    def get_technician(self, tech_id, headers):
        return self._request("GET", f"/qa/technicians/{tech_id}", headers=headers)

    def suspend_technician(self, tech_id, headers):
        return self._request("POST", f"/qa/technicians/{tech_id}/suspend", {}, headers)

    def reinstate_technician(self, tech_id, headers):
        return self._request("POST", f"/qa/technicians/{tech_id}/reinstate", {}, headers)

    def separate_technician(self, tech_id, headers):
        return self._request("POST", f"/qa/technicians/{tech_id}/separate", {}, headers)

    # --- label reconciliations ---
    def create_label_reconciliation(self, payload, headers):
        return self._request("POST", "/qa/label-reconciliations", payload, headers)

    def list_label_reconciliations(self, headers, params=None):
        return self._request("GET", "/qa/label-reconciliations", headers=headers, params=params)

    def get_label_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/qa/label-reconciliations/{recon_id}", headers=headers)

    def resolve_label_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/qa/label-reconciliations/{recon_id}/resolve", {}, headers)

    def escalate_label_reconciliation(self, recon_id, headers):
        return self._request("POST", f"/qa/label-reconciliations/{recon_id}/escalate", {}, headers)

    # --- rework batches ---
    def create_rework_batch(self, payload, headers):
        return self._request("POST", "/qa/rework-batches", payload, headers)

    def list_rework_batches(self, headers, params=None):
        return self._request("GET", "/qa/rework-batches", headers=headers, params=params)

    def get_rework_batch(self, batch_id, headers):
        return self._request("GET", f"/qa/rework-batches/{batch_id}", headers=headers)

    def commit_rework_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/qa/rework-batches/{batch_id}/commit", payload, headers)

    def scrap_rework_batch(self, batch_id, headers):
        return self._request("POST", f"/qa/rework-batches/{batch_id}/scrap", {}, headers)

    # --- incidents ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/qa/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/qa/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/qa/incidents/{incident_id}", headers=headers)

    def begin_incident_investigation(self, incident_id, headers):
        return self._request("POST", f"/qa/incidents/{incident_id}/begin-investigation", {}, headers)

    def contain_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/qa/incidents/{incident_id}/contain", payload, headers)

    def close_incident(self, incident_id, payload, headers):
        return self._request("POST", f"/qa/incidents/{incident_id}/close", payload, headers)

    def void_incident(self, incident_id, headers):
        return self._request("POST", f"/qa/incidents/{incident_id}/void", {}, headers)

    # --- audit findings ---
    def create_audit_finding(self, payload, headers):
        return self._request("POST", "/qa/audit-findings", payload, headers)

    def list_audit_findings(self, headers, params=None):
        return self._request("GET", "/qa/audit-findings", headers=headers, params=params)

    def get_audit_finding(self, finding_id, headers):
        return self._request("GET", f"/qa/audit-findings/{finding_id}", headers=headers)

    def resolve_audit_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/qa/audit-findings/{finding_id}/resolve", payload, headers)

    def waive_audit_finding(self, finding_id, headers):
        return self._request("POST", f"/qa/audit-findings/{finding_id}/waive", {}, headers)


api_client = ApiClient()
