"""API client: one method per endpoint defined in the PRD endpoint table (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.6) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Customers (PRD §3.1) ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customer_formulas(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/api/customers/{customer_id}/formulas", headers=headers, params=params
        )

    # --- Raw materials (PRD §3.2) ---
    def create_raw_material(self, payload, headers):
        return self._request("POST", "/api/raw-materials", payload, headers)

    def get_raw_material(self, material_id, headers):
        return self._request("GET", f"/api/raw-materials/{material_id}", headers=headers)

    def list_raw_material_lots(self, material_id, headers, params=None):
        return self._request(
            "GET", f"/api/raw-materials/{material_id}/material-lots",
            headers=headers, params=params,
        )

    def list_raw_material_formula_lines(self, material_id, headers, params=None):
        return self._request(
            "GET", f"/api/raw-materials/{material_id}/formula-lines",
            headers=headers, params=params,
        )

    # --- Material lots & identity testing (PRD §3.2) ---
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/api/material-lots", payload, headers)

    def get_material_lot(self, lot_id, headers):
        return self._request("GET", f"/api/material-lots/{lot_id}", headers=headers)

    def submit_identity_test(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/api/material-lots/{lot_id}/identity-tests", payload, headers
        )

    def list_identity_tests(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/api/material-lots/{lot_id}/identity-tests",
            headers=headers, params=params,
        )

    def list_lot_consumptions(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/api/material-lots/{lot_id}/consumptions",
            headers=headers, params=params,
        )

    def coa_review_identity_test(self, test_id, payload, headers):
        return self._request(
            "POST", f"/api/identity-tests/{test_id}/coa-review", payload, headers
        )

    # --- Formulas (PRD §3.1) ---
    def create_formula(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/api/customers/{customer_id}/formulas", payload, headers
        )

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/api/formulas/{formula_id}", headers=headers)

    def update_formula(self, formula_id, payload, headers):
        return self._request("PUT", f"/api/formulas/{formula_id}", payload, headers)

    def list_formula_lines(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/api/formulas/{formula_id}/lines", headers=headers, params=params
        )

    def list_formula_revisions(self, formula_id, headers, params=None):
        return self._request(
            "GET", f"/api/formulas/{formula_id}/revisions", headers=headers, params=params
        )

    def approve_formula(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/api/formulas/{formula_id}/approve", payload, headers
        )

    def revise_formula(self, formula_id, payload, headers):
        return self._request(
            "POST", f"/api/formulas/{formula_id}/revise", payload, headers
        )

    # --- Manufacturing orders (PRD §3.3) ---
    def create_manufacturing_order(self, payload, headers):
        return self._request("POST", "/api/manufacturing-orders", payload, headers)

    def list_manufacturing_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/manufacturing-orders", headers=headers, params=params
        )

    def get_manufacturing_order(self, order_id, headers):
        return self._request(
            "GET", f"/api/manufacturing-orders/{order_id}", headers=headers
        )

    def cancel_manufacturing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/manufacturing-orders/{order_id}/cancel", payload, headers
        )

    def schedule_manufacturing_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/manufacturing-orders/{order_id}/schedule", payload, headers
        )

    # --- Batches (PRD §3.4, §3.5) ---
    def list_batches(self, headers, params=None):
        return self._request("GET", "/api/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/api/batches/{batch_id}", headers=headers)

    def start_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/batches/{batch_id}/start", payload, headers)

    def record_consumption(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/batches/{batch_id}/consumptions", payload, headers
        )

    def list_batch_consumptions(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/api/batches/{batch_id}/consumptions", headers=headers, params=params
        )

    def void_consumption(self, batch_id, consumption_id, payload, headers):
        return self._request(
            "POST",
            f"/api/batches/{batch_id}/consumptions/{consumption_id}/void",
            payload,
            headers,
        )

    def complete_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/batches/{batch_id}/complete", payload, headers
        )

    def amend_batch(self, batch_id, payload, headers):
        return self._request("PUT", f"/api/batches/{batch_id}", payload, headers)

    def record_review_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/batches/{batch_id}/record-review", payload, headers
        )

    def release_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/batches/{batch_id}/release", payload, headers)

    def reject_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/batches/{batch_id}/reject", payload, headers)

    # --- Assay results (PRD §3.5) ---
    def submit_assay_result(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/batches/{batch_id}/assay-results", payload, headers
        )

    def list_assay_results(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/api/batches/{batch_id}/assay-results", headers=headers, params=params
        )

    def review_assay_result(self, assay_id, payload, headers):
        return self._request(
            "POST", f"/api/assay-results/{assay_id}/review", payload, headers
        )

    # --- Stability program (PRD §3.7) ---
    def enroll_stability_study(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/api/batches/{batch_id}/stability-studies", payload, headers
        )

    def list_batch_stability_studies(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/api/batches/{batch_id}/stability-studies",
            headers=headers, params=params,
        )

    def complete_stability_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/api/stability-studies/{study_id}/complete", payload, headers
        )

    def create_stability_chamber(self, payload, headers):
        return self._request("POST", "/api/stability-chambers", payload, headers)

    def get_stability_chamber(self, chamber_id, headers):
        return self._request(
            "GET", f"/api/stability-chambers/{chamber_id}", headers=headers
        )

    def list_chamber_stability_studies(self, chamber_id, headers, params=None):
        return self._request(
            "GET", f"/api/stability-chambers/{chamber_id}/stability-studies",
            headers=headers, params=params,
        )

    # --- Production lines & cleaning (PRD §3.6) ---
    def create_production_line(self, payload, headers):
        return self._request("POST", "/api/production-lines", payload, headers)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/api/production-lines/{line_id}", headers=headers)

    def list_cleaning_validations(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/api/production-lines/{line_id}/cleaning-validations",
            headers=headers, params=params,
        )

    def record_cleaning_validation(self, line_id, payload, headers):
        return self._request(
            "POST", f"/api/production-lines/{line_id}/cleaning-validations",
            payload, headers,
        )

    def swab_cleaning_validation(self, validation_id, payload, headers):
        return self._request(
            "POST", f"/api/cleaning-validations/{validation_id}/swab", payload, headers
        )

    def approve_cleaning_validation(self, validation_id, payload, headers):
        return self._request(
            "POST", f"/api/cleaning-validations/{validation_id}/approve", payload, headers
        )

    # --- Recalls (PRD §3.8) ---
    def create_recall(self, payload, headers):
        return self._request("POST", "/api/recalls", payload, headers)

    def close_recall(self, recall_id, payload, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/close", payload, headers)


api_client = ApiClient()
