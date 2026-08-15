"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/tea-ops/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/tea-ops/suppliers/{supplier_id}",
                             headers=headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/tea-ops/suppliers/{supplier_id}/suspend",
                             {}, headers)

    def reinstate_supplier(self, supplier_id, headers):
        return self._request(
            "POST", f"/tea-ops/suppliers/{supplier_id}/reinstate", {}, headers)

    # --- Leaf lots ---
    def create_leaf_lot(self, payload, headers):
        return self._request("POST", "/tea-ops/leaf-lots", payload, headers)

    def get_leaf_lot(self, lot_id, headers):
        return self._request("GET", f"/tea-ops/leaf-lots/{lot_id}",
                             headers=headers)

    def list_leaf_lots(self, headers, params=None):
        return self._request("GET", "/tea-ops/leaf-lots",
                             headers=headers, params=params)

    def create_grade_assessment(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/tea-ops/leaf-lots/{lot_id}/grade-assessments",
            payload, headers)

    def list_grade_assessments(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/tea-ops/leaf-lots/{lot_id}/grade-assessments",
            headers=headers, params=params)

    def create_residue_test(self, lot_id, payload, headers):
        return self._request("POST", f"/tea-ops/leaf-lots/{lot_id}/residue-tests",
                             payload, headers)

    def list_residue_tests(self, lot_id, headers, params=None):
        return self._request("GET", f"/tea-ops/leaf-lots/{lot_id}/residue-tests",
                             headers=headers, params=params)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/tea-ops/leaf-lots/{lot_id}/release",
                             {}, headers)

    def recall_lot(self, lot_id, headers):
        return self._request("POST", f"/tea-ops/leaf-lots/{lot_id}/recall",
                             {}, headers)

    def list_lot_allocations(self, lot_id, headers, params=None):
        return self._request("GET", f"/tea-ops/leaf-lots/{lot_id}/allocations",
                             headers=headers, params=params)

    # --- Flavorings ---
    def create_flavoring(self, payload, headers):
        return self._request("POST", "/tea-ops/flavorings", payload, headers)

    def get_flavoring(self, flavoring_id, headers):
        return self._request("GET", f"/tea-ops/flavorings/{flavoring_id}",
                             headers=headers)

    def retire_flavoring(self, flavoring_id, headers):
        return self._request("POST", f"/tea-ops/flavorings/{flavoring_id}/retire",
                             {}, headers)

    def list_flavoring_applications(self, flavoring_id, headers, params=None):
        return self._request(
            "GET", f"/tea-ops/flavorings/{flavoring_id}/flavoring-applications",
            headers=headers, params=params)

    # --- Blend recipes ---
    def create_recipe(self, payload, headers):
        return self._request("POST", "/tea-ops/recipes", payload, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/tea-ops/recipes/{recipe_id}",
                             headers=headers)

    def list_recipes(self, headers, params=None):
        return self._request("GET", "/tea-ops/recipes",
                             headers=headers, params=params)

    def update_recipe(self, recipe_id, payload, headers):
        return self._request("PUT", f"/tea-ops/recipes/{recipe_id}",
                             payload, headers)

    def activate_recipe(self, recipe_id, headers):
        return self._request("POST", f"/tea-ops/recipes/{recipe_id}/activate",
                             {}, headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/tea-ops/recipes/{recipe_id}/retire",
                             {}, headers)

    # --- Blend batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/tea-ops/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/tea-ops/batches/{batch_id}",
                             headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/tea-ops/batches",
                             headers=headers, params=params)

    def lock_recipe(self, batch_id, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/lock-recipe",
                             {}, headers)

    def create_allocation(self, batch_id, payload, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/allocations",
                             payload, headers)

    def list_batch_allocations(self, batch_id, headers, params=None):
        return self._request("GET", f"/tea-ops/batches/{batch_id}/allocations",
                             headers=headers, params=params)

    def finalize_allocation(self, batch_id, headers):
        return self._request(
            "POST", f"/tea-ops/batches/{batch_id}/finalize-allocation",
            {}, headers)

    def blend_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/blend",
                             payload, headers)

    def apply_flavoring(self, batch_id, payload, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/apply-flavoring",
                             payload, headers)

    def list_batch_flavoring_applications(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/tea-ops/batches/{batch_id}/flavoring-applications",
            headers=headers, params=params)

    def submit_qc(self, batch_id, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/submit-qc",
                             {}, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/release",
                             {}, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/cancel",
                             {}, headers)

    def recall_batch(self, batch_id, headers):
        return self._request("POST", f"/tea-ops/batches/{batch_id}/recall",
                             {}, headers)

    # --- Packaging lines ---
    def create_packaging_line(self, payload, headers):
        return self._request("POST", "/tea-ops/packaging-lines", payload, headers)

    def get_packaging_line(self, line_id, headers):
        return self._request("GET", f"/tea-ops/packaging-lines/{line_id}",
                             headers=headers)

    def enter_maintenance(self, line_id, headers):
        return self._request(
            "POST", f"/tea-ops/packaging-lines/{line_id}/enter-maintenance",
            {}, headers)

    def exit_maintenance(self, line_id, headers):
        return self._request(
            "POST", f"/tea-ops/packaging-lines/{line_id}/exit-maintenance",
            {}, headers)

    # --- Production runs ---
    def create_run(self, payload, headers):
        return self._request("POST", "/tea-ops/runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/tea-ops/runs/{run_id}", headers=headers)

    def list_runs(self, headers, params=None):
        return self._request("GET", "/tea-ops/runs",
                             headers=headers, params=params)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/tea-ops/runs/{run_id}/start",
                             {}, headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/tea-ops/runs/{run_id}/complete",
                             payload, headers)

    def cancel_run(self, run_id, headers):
        return self._request("POST", f"/tea-ops/runs/{run_id}/cancel",
                             {}, headers)

    # --- Private-label contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/tea-ops/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/tea-ops/contracts/{contract_id}",
                             headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/tea-ops/contracts",
                             headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/tea-ops/contracts/{contract_id}/activate",
                             {}, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/tea-ops/contracts/{contract_id}/cancel",
                             {}, headers)

    # --- Certificate grants ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/tea-ops/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/tea-ops/certificates/{certificate_id}",
                             headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/tea-ops/certificates",
                             headers=headers, params=params)

    def suspend_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/tea-ops/certificates/{certificate_id}/suspend",
            {}, headers)

    def reinstate_certificate(self, certificate_id, headers):
        return self._request(
            "POST", f"/tea-ops/certificates/{certificate_id}/reinstate",
            {}, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/tea-ops/_clock/set_current_utc",
                             payload, headers)


api_client = ApiClient()
