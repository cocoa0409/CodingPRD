"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/cosmfg/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/cosmfg/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/cosmfg/customers", headers=headers, params=params)

    # --- Components & lots ---
    def create_component(self, payload, headers):
        return self._request("POST", "/cosmfg/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/cosmfg/components/{component_id}", headers=headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/cosmfg/components", headers=headers, params=params)

    def create_lot(self, component_id, payload, headers):
        return self._request("POST", f"/cosmfg/components/{component_id}/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/cosmfg/lots/{lot_id}", headers=headers)

    def list_lots(self, component_id, headers, params=None):
        return self._request("GET", f"/cosmfg/components/{component_id}/lots", headers=headers, params=params)

    def waive_variant(self, lot_id, payload, headers):
        return self._request("POST", f"/cosmfg/lots/{lot_id}/waive-variant", payload, headers)

    # --- Formulas & regulatory reviews ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/cosmfg/formulas", payload, headers)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/cosmfg/formulas/{formula_id}", headers=headers)

    def list_formulas(self, headers, params=None):
        return self._request("GET", "/cosmfg/formulas", headers=headers, params=params)

    def submit_formula(self, formula_id, headers):
        return self._request("POST", f"/cosmfg/formulas/{formula_id}/submit", headers=headers)

    def activate_formula(self, formula_id, headers):
        return self._request("POST", f"/cosmfg/formulas/{formula_id}/activate", headers=headers)

    def retire_formula(self, formula_id, headers):
        return self._request("POST", f"/cosmfg/formulas/{formula_id}/retire", headers=headers)

    def create_revision(self, formula_id, payload, headers):
        return self._request("POST", f"/cosmfg/formulas/{formula_id}/revisions", payload, headers)

    def list_formula_reviews(self, formula_id, headers, params=None):
        return self._request("GET", f"/cosmfg/formulas/{formula_id}/reviews", headers=headers, params=params)

    def list_formula_studies(self, formula_id, headers, params=None):
        return self._request("GET", f"/cosmfg/formulas/{formula_id}/stability-studies", headers=headers, params=params)

    def create_review(self, formula_id, payload, headers):
        return self._request("POST", f"/cosmfg/formulas/{formula_id}/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/cosmfg/reviews/{review_id}", headers=headers)

    def claim_review(self, review_id, headers):
        return self._request("POST", f"/cosmfg/reviews/{review_id}/claim", headers=headers)

    def approve_review(self, review_id, headers):
        return self._request("POST", f"/cosmfg/reviews/{review_id}/approve", headers=headers)

    def request_changes(self, review_id, payload, headers):
        return self._request("POST", f"/cosmfg/reviews/{review_id}/request-changes", payload, headers)

    def resubmit_review(self, review_id, headers):
        return self._request("POST", f"/cosmfg/reviews/{review_id}/resubmit", headers=headers)

    # --- Production orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/cosmfg/production-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/cosmfg/production-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/cosmfg/production-orders", headers=headers, params=params)

    def patch_order(self, order_id, payload, headers):
        return self._request("PATCH", f"/cosmfg/production-orders/{order_id}", payload, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/cosmfg/production-orders/{order_id}/confirm", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/cosmfg/production-orders/{order_id}/cancel", headers=headers)

    def resume_order(self, order_id, headers):
        return self._request("POST", f"/cosmfg/production-orders/{order_id}/resume", headers=headers)

    def list_order_batches(self, order_id, headers, params=None):
        return self._request("GET", f"/cosmfg/production-orders/{order_id}/batches", headers=headers, params=params)

    def list_order_allocations(self, order_id, headers, params=None):
        return self._request("GET", f"/cosmfg/production-orders/{order_id}/allocations", headers=headers, params=params)

    def list_order_shortfalls(self, order_id, headers, params=None):
        return self._request("GET", f"/cosmfg/production-orders/{order_id}/shortfalls", headers=headers, params=params)

    def list_order_runs(self, order_id, headers, params=None):
        return self._request("GET", f"/cosmfg/production-orders/{order_id}/filling-runs", headers=headers, params=params)

    def create_allocations(self, order_id, payload, headers):
        return self._request("POST", f"/cosmfg/production-orders/{order_id}/allocations", payload, headers)

    # --- Batches & IPC ---
    def create_batch(self, order_id, payload, headers):
        return self._request("POST", f"/cosmfg/production-orders/{order_id}/batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/cosmfg/batches/{batch_id}", headers=headers)

    def list_batch_runs(self, batch_id, headers, params=None):
        return self._request("GET", f"/cosmfg/batches/{batch_id}/filling-runs", headers=headers, params=params)

    def approve_scale_up(self, batch_id, headers):
        return self._request("POST", f"/cosmfg/batches/{batch_id}/approve-scale-up", headers=headers)

    def start_mixing(self, batch_id, headers):
        return self._request("POST", f"/cosmfg/batches/{batch_id}/start-mixing", headers=headers)

    def record_ipc_check(self, batch_id, payload, headers):
        return self._request("POST", f"/cosmfg/batches/{batch_id}/ipc-checks", payload, headers)

    def list_ipc_checks(self, batch_id, headers, params=None):
        return self._request("GET", f"/cosmfg/batches/{batch_id}/ipc-checks", headers=headers, params=params)

    def adjust_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/cosmfg/batches/{batch_id}/adjust", payload, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/cosmfg/batches/{batch_id}/release", headers=headers)

    def reject_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/cosmfg/batches/{batch_id}/reject", payload, headers)

    # --- Shortfalls ---
    def declare_shortfall(self, order_id, payload, headers):
        return self._request("POST", f"/cosmfg/production-orders/{order_id}/shortfalls", payload, headers)

    def get_shortfall(self, shortfall_id, headers):
        return self._request("GET", f"/cosmfg/shortfalls/{shortfall_id}", headers=headers)

    def list_shortfalls(self, headers, params=None):
        return self._request("GET", "/cosmfg/shortfalls", headers=headers, params=params)

    def commit_shortfall(self, shortfall_id, payload, headers):
        return self._request("POST", f"/cosmfg/shortfalls/{shortfall_id}/commit", payload, headers)

    def escalate_shortfall(self, shortfall_id, payload, headers):
        return self._request("POST", f"/cosmfg/shortfalls/{shortfall_id}/escalate", payload, headers)

    # --- Allocations (cross references) ---
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/cosmfg/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/cosmfg/allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/cosmfg/allocations/{allocation_id}/release", headers=headers)

    # --- Stability ---
    def create_chamber(self, payload, headers):
        return self._request("POST", "/cosmfg/stability-chambers", payload, headers)

    def get_chamber(self, chamber_id, headers):
        return self._request("GET", f"/cosmfg/stability-chambers/{chamber_id}", headers=headers)

    def list_chamber_studies(self, chamber_id, headers, params=None):
        return self._request("GET", f"/cosmfg/stability-chambers/{chamber_id}/studies", headers=headers, params=params)

    def create_study(self, formula_id, payload, headers):
        return self._request("POST", f"/cosmfg/formulas/{formula_id}/stability-studies", payload, headers)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/cosmfg/stability-studies/{study_id}", headers=headers)

    def record_reading(self, study_id, payload, headers):
        return self._request("POST", f"/cosmfg/stability-studies/{study_id}/readings", payload, headers)

    def list_readings(self, study_id, headers, params=None):
        return self._request("GET", f"/cosmfg/stability-studies/{study_id}/readings", headers=headers, params=params)

    # --- Filling lines & runs ---
    def create_line(self, payload, headers):
        return self._request("POST", "/cosmfg/filling-lines", payload, headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/cosmfg/filling-lines", headers=headers, params=params)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/cosmfg/filling-lines/{line_id}", headers=headers)

    def list_line_runs(self, line_id, headers, params=None):
        return self._request("GET", f"/cosmfg/filling-lines/{line_id}/runs", headers=headers, params=params)

    def finish_cleaning(self, line_id, headers):
        return self._request("POST", f"/cosmfg/filling-lines/{line_id}/finish-cleaning", headers=headers)

    def create_run(self, order_id, payload, headers):
        return self._request("POST", f"/cosmfg/production-orders/{order_id}/filling-runs", payload, headers)

    def get_run(self, run_id, headers):
        return self._request("GET", f"/cosmfg/filling-runs/{run_id}", headers=headers)

    def start_run(self, run_id, headers):
        return self._request("POST", f"/cosmfg/filling-runs/{run_id}/start", headers=headers)

    def complete_run(self, run_id, payload, headers):
        return self._request("POST", f"/cosmfg/filling-runs/{run_id}/complete", payload, headers)

    def abort_run(self, run_id, headers):
        return self._request("POST", f"/cosmfg/filling-runs/{run_id}/abort", headers=headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
