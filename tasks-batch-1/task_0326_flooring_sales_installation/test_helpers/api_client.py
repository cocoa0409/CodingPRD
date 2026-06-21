"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Registration / actors ----
    def create_customer(self, payload, headers=None):
        return self._request("POST", "/flooring/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/flooring/customers/{customer_id}", headers=headers)

    def create_sales_rep(self, payload, headers=None):
        return self._request("POST", "/flooring/sales-reps", payload, headers=headers)

    def get_sales_rep(self, rep_id, headers):
        return self._request("GET", f"/flooring/sales-reps/{rep_id}", headers=headers)

    # ---- Catalog ----
    def create_product(self, payload, headers):
        return self._request("POST", "/flooring/products", payload, headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/flooring/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/flooring/products", headers=headers, params=params)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/flooring/products/{product_id}/discontinue", headers=headers)

    # ---- Jobs ----
    def create_job(self, payload, headers):
        return self._request("POST", "/flooring/jobs", payload, headers=headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/flooring/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/flooring/jobs", headers=headers, params=params)

    def measure_job(self, job_id, payload, headers):
        return self._request("POST", f"/flooring/jobs/{job_id}/measure", payload, headers=headers)

    def request_remeasure(self, job_id, headers):
        return self._request("POST", f"/flooring/jobs/{job_id}/request-remeasure", headers=headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/flooring/jobs/{job_id}/cancel", headers=headers)

    def list_job_estimates(self, job_id, headers, params=None):
        return self._request("GET", f"/flooring/jobs/{job_id}/estimates", headers=headers, params=params)

    def list_job_material_orders(self, job_id, headers, params=None):
        return self._request("GET", f"/flooring/jobs/{job_id}/material-orders", headers=headers, params=params)

    def list_job_install_slots(self, job_id, headers, params=None):
        return self._request("GET", f"/flooring/jobs/{job_id}/install-slots", headers=headers, params=params)

    def list_job_warranty_claims(self, job_id, headers, params=None):
        return self._request("GET", f"/flooring/jobs/{job_id}/warranty-claims", headers=headers, params=params)

    # ---- Estimates ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/flooring/estimates", payload, headers=headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/flooring/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/flooring/estimates", headers=headers, params=params)

    def issue_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/flooring/estimates/{estimate_id}/issue", payload, headers=headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/flooring/estimates/{estimate_id}/accept", headers=headers)

    def expire_check_estimate(self, estimate_id, headers):
        return self._request("POST", f"/flooring/estimates/{estimate_id}/expire-check", headers=headers)

    # ---- Material orders ----
    def get_material_order(self, order_id, headers):
        return self._request("GET", f"/flooring/material-orders/{order_id}", headers=headers)

    def list_material_orders(self, headers, params=None):
        return self._request("GET", "/flooring/material-orders", headers=headers, params=params)

    def backorder_material_order(self, order_id, headers):
        return self._request("POST", f"/flooring/material-orders/{order_id}/backorder", headers=headers)

    def reorder_material_order(self, order_id, headers):
        return self._request("POST", f"/flooring/material-orders/{order_id}/reorder", headers=headers)

    def receive_material_order(self, order_id, headers):
        return self._request("POST", f"/flooring/material-orders/{order_id}/receive", headers=headers)

    # ---- Crews ----
    def create_install_crew(self, payload, headers):
        return self._request("POST", "/flooring/install-crews", payload, headers=headers)

    def get_install_crew(self, crew_id, headers):
        return self._request("GET", f"/flooring/install-crews/{crew_id}", headers=headers)

    def list_install_crews(self, headers, params=None):
        return self._request("GET", "/flooring/install-crews", headers=headers, params=params)

    def deactivate_install_crew(self, crew_id, headers):
        return self._request("POST", f"/flooring/install-crews/{crew_id}/deactivate", headers=headers)

    def list_crew_install_slots(self, crew_id, headers, params=None):
        return self._request("GET", f"/flooring/install-crews/{crew_id}/install-slots", headers=headers, params=params)

    # ---- Install slots ----
    def create_install_slot(self, payload, headers):
        return self._request("POST", "/flooring/install-slots", payload, headers=headers)

    def get_install_slot(self, slot_id, headers):
        return self._request("GET", f"/flooring/install-slots/{slot_id}", headers=headers)

    def start_install_slot(self, slot_id, headers):
        return self._request("POST", f"/flooring/install-slots/{slot_id}/start", headers=headers)

    def complete_install_slot(self, slot_id, headers):
        return self._request("POST", f"/flooring/install-slots/{slot_id}/complete", headers=headers)

    def cancel_install_slot(self, slot_id, headers):
        return self._request("POST", f"/flooring/install-slots/{slot_id}/cancel", headers=headers)

    # ---- Warranty claims ----
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/flooring/warranty-claims", payload, headers=headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/flooring/warranty-claims/{claim_id}", headers=headers)

    def approve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/flooring/warranty-claims/{claim_id}/approve", payload, headers=headers)

    def deny_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/flooring/warranty-claims/{claim_id}/deny", payload, headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
