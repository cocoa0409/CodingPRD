"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/pole-program"


class ApiClient(GenericApiClient):
    # --- ProgramBudget ---
    def create_budget(self, payload, headers):
        return self._request("POST", f"{BASE}/budgets", payload, headers)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"{BASE}/budgets/{budget_id}", headers=headers)

    # --- InspectionCycle ---
    def create_inspection_cycle(self, payload, headers):
        return self._request("POST", f"{BASE}/inspection-cycles", payload, headers)

    def get_inspection_cycle(self, cycle_id, headers):
        return self._request("GET", f"{BASE}/inspection-cycles/{cycle_id}", headers=headers)

    def open_inspection_cycle(self, cycle_id, headers):
        return self._request("POST", f"{BASE}/inspection-cycles/{cycle_id}/open", {}, headers)

    def reconcile_inspection_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"{BASE}/inspection-cycles/{cycle_id}/reconcile", payload, headers)

    # --- Pole ---
    def create_pole(self, payload, headers):
        return self._request("POST", f"{BASE}/poles", payload, headers)

    def get_pole(self, pole_id, headers):
        return self._request("GET", f"{BASE}/poles/{pole_id}", headers=headers)

    def patch_pole_gis_attributes(self, pole_id, payload, headers):
        return self._request("PATCH", f"{BASE}/poles/{pole_id}/gis-attributes", payload, headers)

    # --- InspectionTask ---
    def create_inspection_task(self, payload, headers):
        return self._request("POST", f"{BASE}/inspection-tasks", payload, headers)

    def list_inspection_tasks(self, headers, params=None):
        return self._request("GET", f"{BASE}/inspection-tasks", headers=headers, params=params)

    def get_inspection_task(self, task_id, headers):
        return self._request("GET", f"{BASE}/inspection-tasks/{task_id}", headers=headers)

    def submit_inspection_task(self, task_id, payload, headers):
        return self._request("POST", f"{BASE}/inspection-tasks/{task_id}/submit", payload, headers)

    def qa_review_inspection_task(self, task_id, payload, headers):
        return self._request("POST", f"{BASE}/inspection-tasks/{task_id}/qa-review", payload, headers)

    def waive_inspection_task(self, task_id, payload, headers):
        return self._request("POST", f"{BASE}/inspection-tasks/{task_id}/waive", payload, headers)

    # --- TreatmentWorkOrder ---
    def create_treatment_work_order(self, payload, headers):
        return self._request("POST", f"{BASE}/treatment-work-orders", payload, headers)

    def list_treatment_work_orders(self, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-work-orders", headers=headers, params=params)

    def get_treatment_work_order(self, order_id, headers):
        return self._request("GET", f"{BASE}/treatment-work-orders/{order_id}", headers=headers)

    def schedule_treatment_work_order(self, order_id, payload, headers):
        return self._request("POST", f"{BASE}/treatment-work-orders/{order_id}/schedule", payload, headers)

    def apply_treatment_work_order(self, order_id, headers):
        return self._request("POST", f"{BASE}/treatment-work-orders/{order_id}/apply", {}, headers)

    def qa_review_treatment_work_order(self, order_id, payload, headers):
        return self._request("POST", f"{BASE}/treatment-work-orders/{order_id}/qa-review", payload, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/warranty-claims", payload, headers)

    def list_warranty_claims_for_order(self, order_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-work-orders/{order_id}/warranty-claims",
                             headers=headers, params=params)

    def adjudicate_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{BASE}/warranty-claims/{claim_id}/adjudicate", payload, headers)

    # --- ContractorCrew ---
    def create_contractor_crew(self, payload, headers):
        return self._request("POST", f"{BASE}/contractor-crews", payload, headers)

    def get_contractor_crew(self, crew_id, headers):
        return self._request("GET", f"{BASE}/contractor-crews/{crew_id}", headers=headers)

    # --- ReplacementWorkOrder ---
    def create_replacement_work_order(self, payload, headers):
        return self._request("POST", f"{BASE}/replacement-work-orders", payload, headers)

    def list_replacement_work_orders(self, headers, params=None):
        return self._request("GET", f"{BASE}/replacement-work-orders", headers=headers, params=params)

    def get_replacement_work_order(self, order_id, headers):
        return self._request("GET", f"{BASE}/replacement-work-orders/{order_id}", headers=headers)

    def fund_replacement_work_order(self, order_id, payload, headers):
        return self._request("POST", f"{BASE}/replacement-work-orders/{order_id}/fund", payload, headers)

    def defund_replacement_work_order(self, order_id, headers):
        return self._request("POST", f"{BASE}/replacement-work-orders/{order_id}/defund", {}, headers)

    def defer_replacement_work_order(self, order_id, headers):
        return self._request("POST", f"{BASE}/replacement-work-orders/{order_id}/defer", {}, headers)

    def complete_replacement_work_order(self, order_id, payload, headers):
        return self._request("POST", f"{BASE}/replacement-work-orders/{order_id}/complete", payload, headers)

    # --- AttachmentAudit ---
    def list_attachment_audits(self, headers, params=None):
        return self._request("GET", f"{BASE}/attachment-audits", headers=headers, params=params)

    def get_attachment_audit(self, audit_id, headers):
        return self._request("GET", f"{BASE}/attachment-audits/{audit_id}", headers=headers)

    def adjudicate_attachment_audit(self, audit_id, headers):
        return self._request("POST", f"{BASE}/attachment-audits/{audit_id}/adjudicate", {}, headers)

    def mark_cured_attachment_audit(self, audit_id, headers):
        return self._request("POST", f"{BASE}/attachment-audits/{audit_id}/mark-cured", {}, headers)

    # --- BacklogSnapshot ---
    def list_backlog_snapshots(self, headers, params=None):
        return self._request("GET", f"{BASE}/backlog-snapshots", headers=headers, params=params)

    def get_backlog_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"{BASE}/backlog-snapshots/{snapshot_id}", headers=headers)

    # --- Logical clock (test-driving) ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
