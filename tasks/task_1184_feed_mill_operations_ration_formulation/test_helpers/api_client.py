"""API client: one method per endpoint defined in the PRD (§4 catalogue)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- ingredients & price ticks ---
    def create_ingredient(self, payload, headers):
        return self._request("POST", "/api/ingredients", payload, headers)

    def get_ingredient(self, ingredient_id, headers):
        return self._request("GET", f"/api/ingredients/{ingredient_id}", headers=headers)

    def discontinue_ingredient(self, ingredient_id, headers):
        return self._request("POST", f"/api/ingredients/{ingredient_id}/discontinue", {}, headers)

    def create_price_tick(self, payload, headers):
        return self._request("POST", "/api/price-ticks", payload, headers)

    def list_price_ticks(self, ingredient_id, headers, params=None):
        return self._request("GET", f"/api/ingredients/{ingredient_id}/price-ticks", headers=headers, params=params)

    # --- contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/api/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/api/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/api/contracts/{contract_id}/cancel", {}, headers)

    # --- bins ---
    def create_bin(self, payload, headers):
        return self._request("POST", "/api/bins", payload, headers)

    def list_bins(self, headers, params=None):
        return self._request("GET", "/api/bins", headers=headers, params=params)

    def get_bin(self, bin_id, headers):
        return self._request("GET", f"/api/bins/{bin_id}", headers=headers)

    def assign_bin(self, bin_id, payload, headers):
        return self._request("POST", f"/api/bins/{bin_id}/assign", payload, headers)

    def replenish_bin(self, bin_id, payload, headers):
        return self._request("POST", f"/api/bins/{bin_id}/replenish", payload, headers)

    def unblock_bin(self, bin_id, headers):
        return self._request("POST", f"/api/bins/{bin_id}/unblock", {}, headers)

    # --- customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/api/customers/{customer_id}", payload, headers)

    def set_customer_status(self, customer_id, payload, headers):
        return self._request("POST", f"/api/customers/{customer_id}/set-status", payload, headers)

    # --- employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/api/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/api/employees/{employee_id}", headers=headers)

    # --- formulas ---
    def create_formula(self, payload, headers):
        return self._request("POST", "/api/formulas", payload, headers)

    def get_formula(self, formula_id, headers):
        return self._request("GET", f"/api/formulas/{formula_id}", headers=headers)

    def optimize_formula(self, formula_id, payload, headers):
        return self._request("POST", f"/api/formulas/{formula_id}/optimize", payload, headers)

    def activate_formula(self, formula_id, headers):
        return self._request("POST", f"/api/formulas/{formula_id}/activate", {}, headers)

    def retire_formula(self, formula_id, headers):
        return self._request("POST", f"/api/formulas/{formula_id}/retire", {}, headers)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/confirm", {}, headers)

    def begin_revision(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/begin-revision", {}, headers)

    def commit_revision(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/commit-revision", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel", {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/complete", {}, headers)

    # --- batches & weighments ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/api/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/api/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/api/batches/{batch_id}", headers=headers)

    def start_batch(self, batch_id, headers):
        return self._request("POST", f"/api/batches/{batch_id}/start", {}, headers)

    def record_weighment(self, batch_id, payload, headers):
        return self._request("POST", f"/api/batches/{batch_id}/weighments", payload, headers)

    def list_weighments(self, headers, params=None):
        return self._request("GET", "/api/weighments", headers=headers, params=params)

    def get_weighment(self, weighment_id, headers):
        return self._request("GET", f"/api/weighments/{weighment_id}", headers=headers)

    def void_weighment(self, weighment_id, headers):
        return self._request("POST", f"/api/weighments/{weighment_id}/void", {}, headers)

    def mix_batch(self, batch_id, headers):
        return self._request("POST", f"/api/batches/{batch_id}/mix", {}, headers)

    def release_batch(self, batch_id, headers):
        return self._request("POST", f"/api/batches/{batch_id}/release", {}, headers)

    def rework_batch(self, batch_id, headers):
        return self._request("POST", f"/api/batches/{batch_id}/rework", {}, headers)

    def reject_batch(self, batch_id, headers):
        return self._request("POST", f"/api/batches/{batch_id}/reject", {}, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/api/batches/{batch_id}/cancel", {}, headers)

    # --- quality samples ---
    def create_sample(self, payload, headers):
        return self._request("POST", "/api/samples", payload, headers)

    def list_samples(self, headers, params=None):
        return self._request("GET", "/api/samples", headers=headers, params=params)

    def get_sample(self, sample_id, headers):
        return self._request("GET", f"/api/samples/{sample_id}", headers=headers)

    def submit_sample_result(self, sample_id, payload, headers):
        return self._request("POST", f"/api/samples/{sample_id}/result", payload, headers)

    # --- flush records ---
    def create_flush_record(self, payload, headers):
        return self._request("POST", "/api/flush-records", payload, headers)

    def list_flush_records(self, headers, params=None):
        return self._request("GET", "/api/flush-records", headers=headers, params=params)

    def get_flush_record(self, flush_record_id, headers):
        return self._request("GET", f"/api/flush-records/{flush_record_id}", headers=headers)

    def verify_flush_record(self, flush_record_id, headers):
        return self._request("POST", f"/api/flush-records/{flush_record_id}/verify", {}, headers)

    def reject_flush_record(self, flush_record_id, headers):
        return self._request("POST", f"/api/flush-records/{flush_record_id}/reject", {}, headers)

    # --- production lines & trucks ---
    def create_line(self, payload, headers):
        return self._request("POST", "/api/lines", payload, headers)

    def get_line(self, line_id, headers):
        return self._request("GET", f"/api/lines/{line_id}", headers=headers)

    def set_line_status(self, line_id, payload, headers):
        return self._request("POST", f"/api/lines/{line_id}/set-status", payload, headers)

    def create_truck(self, payload, headers):
        return self._request("POST", "/api/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/api/trucks/{truck_id}", headers=headers)

    def set_truck_status(self, truck_id, payload, headers):
        return self._request("POST", f"/api/trucks/{truck_id}/set-status", payload, headers)

    # --- delivery trips ---
    def create_trip(self, payload, headers):
        return self._request("POST", "/api/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/api/trips", headers=headers, params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/api/trips/{trip_id}", headers=headers)

    def load_trip(self, trip_id, headers):
        return self._request("POST", f"/api/trips/{trip_id}/load", {}, headers)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/api/trips/{trip_id}/depart", {}, headers)

    def deliver_trip(self, trip_id, headers):
        return self._request("POST", f"/api/trips/{trip_id}/deliver", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/api/trips/{trip_id}/cancel", {}, headers)


api_client = ApiClient()
