"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
POST bodies are passed as JSON; GET query filters are passed via params.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Clock ──
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Customers ──
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def adjust_credit(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-adjustments", payload, headers)

    def create_address(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/addresses", payload, headers)

    def list_addresses(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/addresses", headers=headers, params=params)

    # ── Templates ──
    def create_template(self, payload, headers):
        return self._request("POST", "/templates", payload, headers)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/templates/{template_id}", headers=headers)

    def retire_template(self, template_id, headers):
        return self._request("POST", f"/templates/{template_id}/retire", {}, headers)

    # ── Projects ──
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def upload_photo(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/photos", payload, headers)

    def list_photos(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/photos", headers=headers, params=params)

    def autolayout(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/autolayout", {}, headers)

    def generate_proof(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/proofs", payload, headers)

    def list_proofs(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/proofs", headers=headers, params=params)

    # ── Proofs ──
    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/approve", {}, headers)

    def request_changes(self, proof_id, payload, headers):
        return self._request("POST", f"/proofs/{proof_id}/request-changes", payload, headers)

    # ── Pricing / Orders ──
    def quote_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/quote", payload, headers)

    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    def reorder(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reorder", payload, headers)

    # ── Production & Shipping ──
    def list_production_jobs(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/production-job", headers=headers, params=params)

    def advance_job(self, job_id, headers):
        return self._request("POST", f"/production-jobs/{job_id}/advance", {}, headers)

    def create_shipment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def advance_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/advance", {}, headers)

    # ── Promotions ──
    def create_promotion(self, payload, headers):
        return self._request("POST", "/promotions", payload, headers)

    def get_promotion(self, promotion_id, headers):
        return self._request("GET", f"/promotions/{promotion_id}", headers=headers)

    def create_promo_window(self, promotion_id, payload, headers):
        return self._request("POST", f"/promotions/{promotion_id}/windows", payload, headers)

    def list_promo_windows(self, promotion_id, headers, params=None):
        return self._request("GET", f"/promotions/{promotion_id}/windows", headers=headers, params=params)

    # ── Surge Windows ──
    def create_surge_window(self, payload, headers):
        return self._request("POST", "/surge-windows", payload, headers)

    def get_surge_window(self, surge_window_id, headers):
        return self._request("GET", f"/surge-windows/{surge_window_id}", headers=headers)


api_client = ApiClient()
