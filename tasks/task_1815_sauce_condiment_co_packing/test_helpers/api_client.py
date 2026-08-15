"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- CustomerAccount ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/copack/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/copack/customers/{customer_id}", headers=headers)

    # --- Formula ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/copack/formulas", payload, headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/copack/formulas", headers=headers, params=params)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/copack/formulas/{formula_id}", headers=headers)

    def update_formula(self, formula_id, payload, headers):
        return self._request("PUT", f"/copack/formulas/{formula_id}", payload, headers)

    def reformulate_formula(self, formula_id, headers):
        return self._request(
            "POST", f"/copack/formulas/{formula_id}/reformulate", {}, headers
        )

    # --- IngredientSupply ---
    def create_ingredient_supply(self, payload, headers):
        return self._request("POST", "/copack/ingredient-supplies", payload, headers)

    def list_ingredient_supplies(self, headers, params=None):
        return self._request(
            "GET", "/copack/ingredient-supplies", headers=headers, params=params
        )

    def get_ingredient_supply(self, supply_id, headers):
        return self._request(
            "GET", f"/copack/ingredient-supplies/{supply_id}", headers=headers
        )

    def receive_ingredient_supply(self, supply_id, payload, headers):
        return self._request(
            "POST", f"/copack/ingredient-supplies/{supply_id}/receive", payload, headers
        )

    # --- PilotCell ---
    def create_pilot_cell(self, payload, headers):
        return self._request("POST", "/copack/pilot-cells", payload, headers)

    def get_pilot_cell(self, cell_id, headers):
        return self._request("GET", f"/copack/pilot-cells/{cell_id}", headers=headers)

    # --- ScaleUpTrial ---
    def create_scale_up_trial(self, payload, headers):
        return self._request("POST", "/copack/scale-up-trials", payload, headers)

    def list_scale_up_trials(self, headers, params=None):
        return self._request(
            "GET", "/copack/scale-up-trials", headers=headers, params=params
        )

    def get_scale_up_trial(self, trial_id, headers):
        return self._request(
            "GET", f"/copack/scale-up-trials/{trial_id}", headers=headers
        )

    def record_trial_results(self, trial_id, payload, headers):
        return self._request(
            "POST",
            f"/copack/scale-up-trials/{trial_id}/record-results",
            payload,
            headers,
        )

    def cancel_trial(self, trial_id, headers):
        return self._request(
            "POST", f"/copack/scale-up-trials/{trial_id}/cancel", {}, headers
        )

    # --- ProcessAuthorityLetter ---
    def create_process_authority_letter(self, payload, headers):
        return self._request(
            "POST", "/copack/process-authority-letters", payload, headers
        )

    def list_process_authority_letters(self, headers, params=None):
        return self._request(
            "GET", "/copack/process-authority-letters", headers=headers, params=params
        )

    def get_process_authority_letter(self, letter_id, headers):
        return self._request(
            "GET", f"/copack/process-authority-letters/{letter_id}", headers=headers
        )

    def activate_process_authority_letter(self, letter_id, headers):
        return self._request(
            "POST",
            f"/copack/process-authority-letters/{letter_id}/activate",
            {},
            headers,
        )

    # --- KettleLine ---
    def create_kettle_line(self, payload, headers):
        return self._request("POST", "/copack/kettle-lines", payload, headers)

    def get_kettle_line(self, line_id, headers):
        return self._request("GET", f"/copack/kettle-lines/{line_id}", headers=headers)

    # --- PackagingComponent ---
    def create_packaging_component(self, payload, headers):
        return self._request("POST", "/copack/packaging-components", payload, headers)

    def get_packaging_component(self, component_id, headers):
        return self._request(
            "GET", f"/copack/packaging-components/{component_id}", headers=headers
        )

    def update_packaging_component(self, component_id, payload, headers):
        return self._request(
            "PUT", f"/copack/packaging-components/{component_id}", payload, headers
        )

    # --- ProductionRun ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/copack/production-runs", payload, headers)

    def list_production_runs(self, headers, params=None):
        return self._request(
            "GET", "/copack/production-runs", headers=headers, params=params
        )

    def get_production_run(self, run_id, headers):
        return self._request(
            "GET", f"/copack/production-runs/{run_id}", headers=headers
        )

    def confirm_production_run(self, run_id, headers):
        return self._request(
            "POST", f"/copack/production-runs/{run_id}/confirm", {}, headers
        )

    def complete_production_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/copack/production-runs/{run_id}/complete", payload, headers
        )

    def release_production_run(self, run_id, headers):
        return self._request(
            "POST", f"/copack/production-runs/{run_id}/release", {}, headers
        )

    def cancel_production_run(self, run_id, headers):
        return self._request(
            "POST", f"/copack/production-runs/{run_id}/cancel", {}, headers
        )

    # --- QualityHold ---
    def create_quality_hold(self, payload, headers):
        return self._request("POST", "/copack/quality-holds", payload, headers)

    def list_quality_holds(self, headers, params=None):
        return self._request("GET", "/copack/quality-holds", headers=headers, params=params)

    def get_quality_hold(self, hold_id, headers):
        return self._request("GET", f"/copack/quality-holds/{hold_id}", headers=headers)

    def disposition_quality_hold(self, hold_id, payload, headers):
        return self._request(
            "POST", f"/copack/quality-holds/{hold_id}/disposition", payload, headers
        )

    # --- LabelApproval ---
    def create_label_approval(self, payload, headers):
        return self._request("POST", "/copack/label-approvals", payload, headers)

    def list_label_approvals(self, headers, params=None):
        return self._request(
            "GET", "/copack/label-approvals", headers=headers, params=params
        )

    def get_label_approval(self, label_id, headers):
        return self._request(
            "GET", f"/copack/label-approvals/{label_id}", headers=headers
        )

    def submit_label_approval(self, label_id, headers):
        return self._request(
            "POST", f"/copack/label-approvals/{label_id}/submit", {}, headers
        )

    def review_label_approval(self, label_id, payload, headers):
        return self._request(
            "POST", f"/copack/label-approvals/{label_id}/review", payload, headers
        )


api_client = ApiClient()
