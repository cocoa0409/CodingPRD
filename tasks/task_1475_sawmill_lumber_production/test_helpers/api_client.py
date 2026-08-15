"""API client: one method per endpoint defined in the PRD endpoint catalogue."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- Log loads ---
    def create_log_load(self, payload, headers):
        return self._request("POST", "/api/log-loads", payload, headers)

    def list_log_loads(self, headers, params=None):
        return self._request("GET", "/api/log-loads", headers=headers, params=params)

    def get_log_load(self, load_id, headers):
        return self._request("GET", f"/api/log-loads/{load_id}", headers=headers)

    def scale_log_load(self, load_id, payload, headers):
        return self._request("POST", f"/api/log-loads/{load_id}/scale", payload, headers)

    def dispute_log_load(self, load_id, payload, headers):
        return self._request("POST", f"/api/log-loads/{load_id}/dispute", payload, headers)

    def resolve_scale_log_load(self, load_id, payload, headers):
        return self._request("POST", f"/api/log-loads/{load_id}/resolve-scale", payload, headers)

    def deck_log_load(self, load_id, headers):
        return self._request("POST", f"/api/log-loads/{load_id}/deck", {}, headers)

    def undeck_log_load(self, load_id, headers):
        return self._request("POST", f"/api/log-loads/{load_id}/undeck", {}, headers)

    # --- Sawing runs ---
    def create_sawing_run(self, payload, headers):
        return self._request("POST", "/api/sawing-runs", payload, headers)

    def get_sawing_run(self, run_id, headers):
        return self._request("GET", f"/api/sawing-runs/{run_id}", headers=headers)

    def complete_sawing_run(self, run_id, payload, headers):
        return self._request("POST", f"/api/sawing-runs/{run_id}/complete", payload, headers)

    # --- Kiln charges ---
    def create_kiln_charge(self, payload, headers):
        return self._request("POST", "/api/kiln-charges", payload, headers)

    def get_kiln_charge(self, charge_id, headers):
        return self._request("GET", f"/api/kiln-charges/{charge_id}", headers=headers)

    def start_kiln_charge(self, charge_id, headers):
        return self._request("POST", f"/api/kiln-charges/{charge_id}/start", {}, headers)

    def complete_kiln_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/api/kiln-charges/{charge_id}/complete", payload, headers)

    def abort_kiln_charge(self, charge_id, headers):
        return self._request("POST", f"/api/kiln-charges/{charge_id}/abort", {}, headers)

    # --- Lumber packages / grade inspections ---
    def list_lumber_packages(self, headers, params=None):
        return self._request("GET", "/api/lumber-packages", headers=headers, params=params)

    def get_lumber_package(self, package_id, headers):
        return self._request("GET", f"/api/lumber-packages/{package_id}", headers=headers)

    def create_grade_inspection(self, package_id, payload, headers):
        return self._request(
            "POST", f"/api/lumber-packages/{package_id}/grade-inspections", payload, headers
        )

    def list_grade_inspections(self, package_id, headers):
        return self._request(
            "GET", f"/api/lumber-packages/{package_id}/grade-inspections", headers=headers
        )

    # --- Price lists ---
    def create_price_list(self, payload, headers):
        return self._request("POST", "/api/price-lists", payload, headers)

    # --- Sales contracts ---
    def create_sales_contract(self, payload, headers):
        return self._request("POST", "/api/sales-contracts", payload, headers)

    def get_sales_contract(self, contract_id, headers):
        return self._request("GET", f"/api/sales-contracts/{contract_id}", headers=headers)

    def activate_sales_contract(self, contract_id, headers):
        return self._request("POST", f"/api/sales-contracts/{contract_id}/activate", {}, headers)

    def amend_sales_contract(self, contract_id, payload, headers):
        return self._request("PUT", f"/api/sales-contracts/{contract_id}", payload, headers)

    # --- Sales orders ---
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/api/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/api/sales-orders", headers=headers, params=params)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/api/sales-orders/{order_id}", headers=headers)

    def allocate_sales_order(self, order_id, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/allocate", {}, headers)

    def ship_sales_order(self, order_id, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/ship", {}, headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/api/sales-orders/{order_id}/cancel", {}, headers)

    # --- Byproducts / ops ---
    def create_byproduct_sale(self, payload, headers):
        return self._request("POST", "/api/byproduct-sales", payload, headers)

    def get_byproduct_inventory(self, headers):
        return self._request("GET", "/api/byproduct-inventory", headers=headers)

    def create_ops_run(self, headers):
        return self._request("POST", "/api/ops/runs", {}, headers)


api_client = ApiClient()
