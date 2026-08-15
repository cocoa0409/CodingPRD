"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/petfood/_clock/set_current_utc", payload, headers)

    # --- BrandOwner ---
    def create_brand_owner(self, payload, headers):
        return self._request("POST", "/petfood/brand-owners", payload, headers)

    def get_brand_owner(self, brand_owner_id, headers):
        return self._request("GET", f"/petfood/brand-owners/{brand_owner_id}", headers=headers)

    def list_brand_owners(self, headers, params=None):
        return self._request("GET", "/petfood/brand-owners", headers=headers, params=params)

    def list_brand_owner_complaint_cases(self, brand_owner_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/brand-owners/{brand_owner_id}/complaint-cases",
            headers=headers, params=params,
        )

    # --- Supplier ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/petfood/suppliers", payload, headers)

    def approve_supplier(self, supplier_id, headers):
        return self._request("POST", f"/petfood/suppliers/{supplier_id}/approve", {}, headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/petfood/suppliers/{supplier_id}/suspend", {}, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/petfood/suppliers/{supplier_id}", headers=headers)

    def list_supplier_ingredient_approvals(self, supplier_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/suppliers/{supplier_id}/ingredient-approvals",
            headers=headers, params=params,
        )

    # --- Ingredient ---
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/petfood/ingredients", payload, headers)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/petfood/ingredients/{ingredient_id}", headers=headers)

    def list_ingredients(self, headers, params=None):
        return self._request("GET", "/petfood/ingredients", headers=headers, params=params)

    # --- SupplierIngredientApproval ---
    def create_pairing(self, payload, headers):
        return self._request("POST", "/petfood/supplier-ingredient-approvals", payload, headers)

    def approve_pairing(self, pairing_id, headers):
        return self._request(
            "POST", f"/petfood/supplier-ingredient-approvals/{pairing_id}/approve", {}, headers
        )

    def reject_pairing(self, pairing_id, headers):
        return self._request(
            "POST", f"/petfood/supplier-ingredient-approvals/{pairing_id}/reject", {}, headers
        )

    def revoke_pairing(self, pairing_id, headers):
        return self._request(
            "POST", f"/petfood/supplier-ingredient-approvals/{pairing_id}/revoke", {}, headers
        )

    def get_pairing(self, pairing_id, headers):
        return self._request(
            "GET", f"/petfood/supplier-ingredient-approvals/{pairing_id}", headers=headers
        )

    # --- Formula ---
    def create_formula(self, brand_owner_id, payload, headers):
        return self._request(
            "POST", f"/petfood/brand-owners/{brand_owner_id}/formulas", payload, headers
        )

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/petfood/formulas/{formula_id}", headers=headers)

    def list_formula_ingredients(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/formulas/{formula_id}/ingredients", headers=headers, params=params
        )

    def add_formula_ingredient(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/ingredients", payload, headers
        )

    def submit_nutrient_review(self, formula_id, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/submit-nutrient-review", {}, headers
        )

    def request_revision(self, formula_id, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/request-revision", {}, headers
        )

    def substantiate_formula(self, formula_id, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/substantiate", {}, headers
        )

    def lock_formula(self, formula_id, headers):
        return self._request("POST", f"/petfood/formulas/{formula_id}/lock", {}, headers)

    def withdraw_formula(self, formula_id, headers):
        return self._request("POST", f"/petfood/formulas/{formula_id}/withdraw", {}, headers)

    # --- NutrientProfile ---
    def create_nutrient_profile(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/nutrient-profiles", payload, headers
        )

    def list_nutrient_profiles(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/formulas/{formula_id}/nutrient-profiles",
            headers=headers, params=params,
        )

    # --- FeedingTrialProtocol ---
    def create_trial_protocol(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/feeding-trial-protocols", payload, headers
        )

    def get_trial_protocol(self, protocol_id, headers):
        return self._request(
            "GET", f"/petfood/feeding-trial-protocols/{protocol_id}", headers=headers
        )

    def list_trial_protocols(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/formulas/{formula_id}/feeding-trial-protocols",
            headers=headers, params=params,
        )

    def open_enrollment(self, protocol_id, headers):
        return self._request(
            "POST", f"/petfood/feeding-trial-protocols/{protocol_id}/open-enrollment", {}, headers
        )

    def enroll(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/petfood/feeding-trial-protocols/{protocol_id}/enroll", payload, headers
        )

    def start_trial(self, protocol_id, headers):
        return self._request(
            "POST", f"/petfood/feeding-trial-protocols/{protocol_id}/start-trial", {}, headers
        )

    def complete_observation(self, protocol_id, payload, headers):
        return self._request(
            "POST", f"/petfood/feeding-trial-protocols/{protocol_id}/complete-observation",
            payload, headers,
        )

    def record_verdict(self, protocol_id, headers, payload=None):
        return self._request(
            "POST", f"/petfood/feeding-trial-protocols/{protocol_id}/record-verdict",
            payload or {}, headers,
        )

    def abort_trial(self, protocol_id, headers):
        return self._request(
            "POST", f"/petfood/feeding-trial-protocols/{protocol_id}/abort", {}, headers
        )

    # --- ProductionBatch ---
    def create_batch(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/production-batches", payload, headers
        )

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/petfood/production-batches/{batch_id}", headers=headers)

    def list_formula_batches(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/formulas/{formula_id}/production-batches",
            headers=headers, params=params,
        )

    def release_batch(self, batch_id, headers):
        return self._request(
            "POST", f"/petfood/production-batches/{batch_id}/release", {}, headers
        )

    def start_run(self, batch_id, headers):
        return self._request(
            "POST", f"/petfood/production-batches/{batch_id}/start-run", {}, headers
        )

    def hold_batch(self, batch_id, headers):
        return self._request("POST", f"/petfood/production-batches/{batch_id}/hold", {}, headers)

    def resume_batch(self, batch_id, headers):
        return self._request("POST", f"/petfood/production-batches/{batch_id}/resume", {}, headers)

    def complete_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/petfood/production-batches/{batch_id}/complete", payload, headers
        )

    def reject_batch(self, batch_id, headers):
        return self._request("POST", f"/petfood/production-batches/{batch_id}/reject", {}, headers)

    # --- BatchLotCode ---
    def create_lot(self, batch_id, payload, headers):
        return self._request("POST", f"/petfood/production-batches/{batch_id}/lots", payload, headers)

    def list_lots(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/production-batches/{batch_id}/lots", headers=headers, params=params
        )

    # --- LabSample / GuaranteedAnalysisReport ---
    def create_lab_sample(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/petfood/production-batches/{batch_id}/lab-samples", payload, headers
        )

    def list_lab_samples(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/production-batches/{batch_id}/lab-samples",
            headers=headers, params=params,
        )

    def create_ga_report(self, batch_id, headers):
        return self._request(
            "POST", f"/petfood/production-batches/{batch_id}/ga-reports", {}, headers
        )

    def list_ga_reports(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/production-batches/{batch_id}/ga-reports",
            headers=headers, params=params,
        )

    # --- StateRegistration ---
    def create_state_registration(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/petfood/formulas/{formula_id}/state-registrations", payload, headers
        )

    def get_state_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/petfood/state-registrations/{registration_id}", headers=headers
        )

    def list_state_registrations(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/formulas/{formula_id}/state-registrations",
            headers=headers, params=params,
        )

    def accept_registration_for_review(self, registration_id, headers):
        return self._request(
            "POST", f"/petfood/state-registrations/{registration_id}/accept-for-review",
            {}, headers,
        )

    def approve_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/petfood/state-registrations/{registration_id}/approve", payload, headers
        )

    def reject_registration(self, registration_id, headers):
        return self._request(
            "POST", f"/petfood/state-registrations/{registration_id}/reject", {}, headers
        )

    def resubmit_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/petfood/state-registrations/{registration_id}/resubmit", payload, headers
        )

    # --- ComplaintCase ---
    def create_complaint_case(self, payload, headers):
        return self._request("POST", "/petfood/complaint-cases", payload, headers)

    def get_complaint_case(self, case_id, headers):
        return self._request("GET", f"/petfood/complaint-cases/{case_id}", headers=headers)

    def list_formula_complaint_cases(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/formulas/{formula_id}/complaint-cases",
            headers=headers, params=params,
        )

    def triage_complaint(self, case_id, payload, headers):
        return self._request("POST", f"/petfood/complaint-cases/{case_id}/triage", payload, headers)

    def open_investigation(self, case_id, headers):
        return self._request(
            "POST", f"/petfood/complaint-cases/{case_id}/open-investigation", {}, headers
        )

    def resolve_complaint(self, case_id, headers):
        return self._request("POST", f"/petfood/complaint-cases/{case_id}/resolve", {}, headers)

    def escalate_complaint(self, case_id, headers):
        return self._request("POST", f"/petfood/complaint-cases/{case_id}/escalate", {}, headers)

    def close_complaint_no_action(self, case_id, headers):
        return self._request(
            "POST", f"/petfood/complaint-cases/{case_id}/close-no-action", {}, headers
        )

    # --- RecallAction ---
    def create_recall_action(self, payload, headers):
        return self._request("POST", "/petfood/recall-actions", payload, headers)

    def get_recall_action(self, recall_id, headers):
        return self._request("GET", f"/petfood/recall-actions/{recall_id}", headers=headers)

    def list_recall_actions(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/petfood/formulas/{formula_id}/recall-actions",
            headers=headers, params=params,
        )

    def begin_effectiveness_check(self, recall_id, headers):
        return self._request(
            "POST", f"/petfood/recall-actions/{recall_id}/begin-effectiveness-check", {}, headers
        )

    def record_effectiveness(self, recall_id, payload, headers):
        return self._request(
            "POST", f"/petfood/recall-actions/{recall_id}/record-effectiveness", payload, headers
        )

    def close_recall(self, recall_id, headers):
        return self._request("POST", f"/petfood/recall-actions/{recall_id}/close", {}, headers)

    def terminate_recall(self, recall_id, headers):
        return self._request("POST", f"/petfood/recall-actions/{recall_id}/terminate", {}, headers)


api_client = ApiClient()
