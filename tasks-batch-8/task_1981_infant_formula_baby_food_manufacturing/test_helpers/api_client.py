"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- System / test-driving ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- SystemUser ---
    def create_system_user(self, payload, headers):
        return self._request("POST", "/api/v1/system-users", payload, headers)

    def list_system_users(self, headers, params=None):
        return self._request("GET", "/api/v1/system-users", headers=headers, params=params)

    def get_system_user(self, user_id, headers):
        return self._request("GET", f"/api/v1/system-users/{user_id}", headers=headers)

    # --- NutrientProfile ---
    def create_nutrient_profile(self, payload, headers):
        return self._request("POST", "/api/v1/nutrient-profiles", payload, headers)

    def list_nutrient_profiles(self, headers, params=None):
        return self._request("GET", "/api/v1/nutrient-profiles", headers=headers, params=params)

    def get_nutrient_profile(self, profile_id, headers):
        return self._request("GET", f"/api/v1/nutrient-profiles/{profile_id}", headers=headers)

    def submit_nutrient_profile(self, profile_id, headers):
        return self._request("POST", f"/api/v1/nutrient-profiles/{profile_id}/submit", {}, headers)

    def approve_nutrient_profile(self, profile_id, headers):
        return self._request("POST", f"/api/v1/nutrient-profiles/{profile_id}/approve", {}, headers)

    def return_nutrient_profile_for_revision(self, profile_id, headers):
        return self._request("POST", f"/api/v1/nutrient-profiles/{profile_id}/return-for-revision", {}, headers)

    def withdraw_nutrient_profile(self, profile_id, headers):
        return self._request("POST", f"/api/v1/nutrient-profiles/{profile_id}/withdraw", {}, headers)

    # --- Supplier ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/api/v1/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/api/v1/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/api/v1/suppliers/{supplier_id}", headers=headers)

    def suspend_supplier(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/v1/suppliers/{supplier_id}/suspend", payload, headers)

    def reinstate_supplier(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/v1/suppliers/{supplier_id}/reinstate", payload, headers)

    def disqualify_supplier(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/v1/suppliers/{supplier_id}/disqualify", payload, headers)

    # --- AuditRecord ---
    def create_audit(self, supplier_id, payload, headers):
        return self._request("POST", f"/api/v1/suppliers/{supplier_id}/audits", payload, headers)

    def list_audits(self, supplier_id, headers, params=None):
        return self._request("GET", f"/api/v1/suppliers/{supplier_id}/audits", headers=headers, params=params)

    def get_audit_record(self, audit_id, headers):
        return self._request("GET", f"/api/v1/audit-records/{audit_id}", headers=headers)

    # --- Ingredient ---
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/api/v1/ingredients", payload, headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/api/v1/ingredients", headers=headers, params=params)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/api/v1/ingredients/{ingredient_id}", headers=headers)

    def list_ingredient_lots_for_ingredient(self, ingredient_id, headers, params=None):
        return self._request("GET", f"/api/v1/ingredients/{ingredient_id}/lots", headers=headers, params=params)

    # --- IngredientLot ---
    def create_ingredient_lot(self, payload, headers):
        return self._request("POST", "/api/v1/ingredient-lots", payload, headers)

    def list_ingredient_lots(self, headers, params=None):
        return self._request("GET", "/api/v1/ingredient-lots", headers=headers, params=params)

    def get_ingredient_lot(self, lot_id, headers):
        return self._request("GET", f"/api/v1/ingredient-lots/{lot_id}", headers=headers)

    def list_lots_for_supplier(self, supplier_id, headers, params=None):
        return self._request("GET", f"/api/v1/suppliers/{supplier_id}/lots", headers=headers, params=params)

    def qc_pass_lot(self, lot_id, headers):
        return self._request("POST", f"/api/v1/ingredient-lots/{lot_id}/qc-pass", {}, headers)

    def qc_fail_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/v1/ingredient-lots/{lot_id}/qc-fail", payload, headers)

    def quarantine_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/api/v1/ingredient-lots/{lot_id}/quarantine", payload, headers)

    def release_quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/api/v1/ingredient-lots/{lot_id}/release-quarantine", {}, headers)

    # --- Formula ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/api/v1/formulas", payload, headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/api/v1/formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/api/v1/formulas/{formula_id}", headers=headers)

    def submit_formula_for_review(self, formula_id, headers):
        return self._request("POST", f"/api/v1/formulas/{formula_id}/submit-for-review", {}, headers)

    def approve_formula(self, formula_id, headers):
        return self._request("POST", f"/api/v1/formulas/{formula_id}/approve", {}, headers)

    def return_formula_for_revision(self, formula_id, headers):
        return self._request("POST", f"/api/v1/formulas/{formula_id}/return-for-revision", {}, headers)

    def activate_formula(self, formula_id, headers):
        return self._request("POST", f"/api/v1/formulas/{formula_id}/activate", {}, headers)

    def discontinue_formula(self, formula_id, headers):
        return self._request("POST", f"/api/v1/formulas/{formula_id}/discontinue", {}, headers)

    def list_formula_batches(self, formula_id, headers, params=None):
        return self._request("GET", f"/api/v1/formulas/{formula_id}/batches", headers=headers, params=params)

    def list_formula_process_validations(self, formula_id, headers, params=None):
        return self._request("GET", f"/api/v1/formulas/{formula_id}/process-validations", headers=headers, params=params)

    def list_formula_label_submissions(self, formula_id, headers, params=None):
        return self._request("GET", f"/api/v1/formulas/{formula_id}/label-submissions", headers=headers, params=params)

    # --- ProcessValidation ---
    def create_process_validation(self, payload, headers):
        return self._request("POST", "/api/v1/process-validations", payload, headers)

    def list_process_validations(self, headers, params=None):
        return self._request("GET", "/api/v1/process-validations", headers=headers, params=params)

    def get_process_validation(self, validation_id, headers):
        return self._request("GET", f"/api/v1/process-validations/{validation_id}", headers=headers)

    def start_process_validation(self, validation_id, headers):
        return self._request("POST", f"/api/v1/process-validations/{validation_id}/start", {}, headers)

    def complete_process_validation(self, validation_id, payload, headers):
        return self._request("POST", f"/api/v1/process-validations/{validation_id}/complete", payload, headers)

    def fail_process_validation(self, validation_id, payload, headers):
        return self._request("POST", f"/api/v1/process-validations/{validation_id}/fail", payload, headers)

    # --- ProductionBatch ---
    def create_production_batch(self, payload, headers):
        return self._request("POST", "/api/v1/production-batches", payload, headers)

    def list_production_batches(self, headers, params=None):
        return self._request("GET", "/api/v1/production-batches", headers=headers, params=params)

    def get_production_batch(self, batch_id, headers):
        return self._request("GET", f"/api/v1/production-batches/{batch_id}", headers=headers)

    def start_production(self, batch_id, headers):
        return self._request("POST", f"/api/v1/production-batches/{batch_id}/start-production", {}, headers)

    def complete_blending(self, batch_id, headers):
        return self._request("POST", f"/api/v1/production-batches/{batch_id}/complete-blending", {}, headers)

    def complete_processing(self, batch_id, payload, headers):
        return self._request("POST", f"/api/v1/production-batches/{batch_id}/complete-processing", payload, headers)

    def submit_for_testing(self, batch_id, headers):
        return self._request("POST", f"/api/v1/production-batches/{batch_id}/submit-for-testing", {}, headers)

    def submit_test_results(self, batch_id, payload, headers):
        return self._request("POST", f"/api/v1/production-batches/{batch_id}/submit-test-results", payload, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/api/v1/production-batches/{batch_id}/release", {}, headers)

    def reject_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/v1/production-batches/{batch_id}/reject", payload, headers)

    # --- LabelSubmission ---
    def create_label_submission(self, payload, headers):
        return self._request("POST", "/api/v1/label-submissions", payload, headers)

    def list_label_submissions(self, headers, params=None):
        return self._request("GET", "/api/v1/label-submissions", headers=headers, params=params)

    def get_label_submission(self, submission_id, headers):
        return self._request("GET", f"/api/v1/label-submissions/{submission_id}", headers=headers)

    def submit_label(self, submission_id, headers):
        return self._request("POST", f"/api/v1/label-submissions/{submission_id}/submit", {}, headers)

    def assign_label_reviewer(self, submission_id, payload, headers):
        return self._request("POST", f"/api/v1/label-submissions/{submission_id}/assign-reviewer", payload, headers)

    def approve_label(self, submission_id, headers):
        return self._request("POST", f"/api/v1/label-submissions/{submission_id}/approve", {}, headers)

    def reject_label(self, submission_id, payload, headers):
        return self._request("POST", f"/api/v1/label-submissions/{submission_id}/reject", payload, headers)

    def return_label_for_revision(self, submission_id, headers):
        return self._request("POST", f"/api/v1/label-submissions/{submission_id}/return-for-revision", {}, headers)

    def withdraw_label(self, submission_id, headers):
        return self._request("POST", f"/api/v1/label-submissions/{submission_id}/withdraw", {}, headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/api/v1/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/api/v1/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/api/v1/complaints/{complaint_id}", headers=headers)

    def start_complaint_investigation(self, complaint_id, headers):
        return self._request("POST", f"/api/v1/complaints/{complaint_id}/start-investigation", {}, headers)

    def escalate_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/v1/complaints/{complaint_id}/escalate", payload, headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/api/v1/complaints/{complaint_id}/resolve", payload, headers)

    def close_complaint(self, complaint_id, headers):
        return self._request("POST", f"/api/v1/complaints/{complaint_id}/close", {}, headers)

    # --- RecallCampaign ---
    def create_recall_campaign(self, payload, headers):
        return self._request("POST", "/api/v1/recall-campaigns", payload, headers)

    def list_recall_campaigns(self, headers, params=None):
        return self._request("GET", "/api/v1/recall-campaigns", headers=headers, params=params)

    def get_recall_campaign(self, recall_id, headers):
        return self._request("GET", f"/api/v1/recall-campaigns/{recall_id}", headers=headers)

    def notify_recall_campaign(self, recall_id, headers):
        return self._request("POST", f"/api/v1/recall-campaigns/{recall_id}/notify", {}, headers)

    def begin_recall_recovery(self, recall_id, headers):
        return self._request("POST", f"/api/v1/recall-campaigns/{recall_id}/begin-recovery", {}, headers)

    def start_effectiveness_check(self, recall_id, headers):
        return self._request("POST", f"/api/v1/recall-campaigns/{recall_id}/start-effectiveness-check", {}, headers)

    def complete_recall_campaign(self, recall_id, headers):
        return self._request("POST", f"/api/v1/recall-campaigns/{recall_id}/complete", {}, headers)

    def terminate_recall_campaign(self, recall_id, payload, headers):
        return self._request("POST", f"/api/v1/recall-campaigns/{recall_id}/terminate", payload, headers)

    # --- RecallScope ---
    def create_recall_scope(self, recall_id, payload, headers):
        return self._request("POST", f"/api/v1/recall-campaigns/{recall_id}/scopes", payload, headers)

    def list_recall_scopes_for_campaign(self, recall_id, headers, params=None):
        return self._request("GET", f"/api/v1/recall-campaigns/{recall_id}/scopes", headers=headers, params=params)

    def list_recall_scopes(self, headers, params=None):
        return self._request("GET", "/api/v1/recall-scopes", headers=headers, params=params)

    def get_recall_scope(self, scope_id, headers):
        return self._request("GET", f"/api/v1/recall-scopes/{scope_id}", headers=headers)

    def record_scope_recovery(self, scope_id, payload, headers):
        return self._request("POST", f"/api/v1/recall-scopes/{scope_id}/record-recovery", payload, headers)

    def verify_recall_scope(self, scope_id, headers):
        return self._request("POST", f"/api/v1/recall-scopes/{scope_id}/verify", {}, headers)

    # --- AllocationPlan ---
    def create_allocation_plan(self, payload, headers):
        return self._request("POST", "/api/v1/allocation-plans", payload, headers)

    def list_allocation_plans(self, headers, params=None):
        return self._request("GET", "/api/v1/allocation-plans", headers=headers, params=params)

    def get_allocation_plan(self, plan_id, headers):
        return self._request("GET", f"/api/v1/allocation-plans/{plan_id}", headers=headers)

    def activate_allocation_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/api/v1/allocation-plans/{plan_id}/activate", payload, headers)

    def cancel_allocation_plan(self, plan_id, headers):
        return self._request("POST", f"/api/v1/allocation-plans/{plan_id}/cancel", {}, headers)

    # --- AllocationEntry ---
    def create_allocation_entry(self, plan_id, payload, headers):
        return self._request("POST", f"/api/v1/allocation-plans/{plan_id}/entries", payload, headers)

    def list_allocation_entries(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/v1/allocation-plans/{plan_id}/entries", headers=headers, params=params)

    def get_allocation_entry(self, entry_id, headers):
        return self._request("GET", f"/api/v1/allocation-entries/{entry_id}", headers=headers)

    def record_fulfillment(self, entry_id, payload, headers):
        return self._request("POST", f"/api/v1/allocation-entries/{entry_id}/record-fulfillment", payload, headers)

    def mark_shortfall(self, entry_id, payload, headers):
        return self._request("POST", f"/api/v1/allocation-entries/{entry_id}/mark-shortfall", payload, headers)


api_client = ApiClient()
