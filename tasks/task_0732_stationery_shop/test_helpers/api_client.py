"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_designs(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/designs", headers=headers, params=params)

    def list_customer_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/orders", headers=headers, params=params)

    # ---- Designers ----
    def create_designer(self, payload, headers):
        return self._request("POST", "/designers", payload, headers)

    def get_designer(self, designer_id, headers):
        return self._request("GET", f"/designers/{designer_id}", headers=headers)

    def list_designers(self, headers, params=None):
        return self._request("GET", "/designers", headers=headers, params=params)

    # ---- Paper stocks ----
    def create_paper_stock(self, payload, headers):
        return self._request("POST", "/paper-stocks", payload, headers)

    def discontinue_paper_stock(self, paper_stock_id, headers):
        return self._request("POST", f"/paper-stocks/{paper_stock_id}/discontinue", headers=headers)

    def patch_paper_stock(self, paper_stock_id, payload, headers):
        return self._request("PATCH", f"/paper-stocks/{paper_stock_id}", payload, headers)

    def get_paper_stock(self, paper_stock_id, headers):
        return self._request("GET", f"/paper-stocks/{paper_stock_id}", headers=headers)

    def list_paper_stocks(self, headers, params=None):
        return self._request("GET", "/paper-stocks", headers=headers, params=params)

    # ---- Finish options ----
    def create_finish_option(self, payload, headers):
        return self._request("POST", "/finish-options", payload, headers)

    def get_finish_option(self, finish_option_id, headers):
        return self._request("GET", f"/finish-options/{finish_option_id}", headers=headers)

    def list_finish_options(self, headers, params=None):
        return self._request("GET", "/finish-options", headers=headers, params=params)

    # ---- Event packages ----
    def create_event_package(self, payload, headers):
        return self._request("POST", "/event-packages", payload, headers)

    def get_event_package(self, event_package_id, headers):
        return self._request("GET", f"/event-packages/{event_package_id}", headers=headers)

    def list_event_packages(self, headers, params=None):
        return self._request("GET", "/event-packages", headers=headers, params=params)

    # ---- Designs ----
    def create_design(self, payload, headers):
        return self._request("POST", "/designs", payload, headers)

    def get_design(self, design_id, headers):
        return self._request("GET", f"/designs/{design_id}", headers=headers)

    def patch_design(self, design_id, payload, headers):
        return self._request("PATCH", f"/designs/{design_id}", payload, headers)

    def list_designs(self, headers, params=None):
        return self._request("GET", "/designs", headers=headers, params=params)

    # ---- Proofs ----
    def create_proof(self, design_id, payload, headers):
        return self._request("POST", f"/designs/{design_id}/proofs", payload, headers)

    def submit_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/submit", headers=headers)

    def request_changes_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/request-changes", headers=headers)

    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/proofs/{proof_id}/approve", headers=headers)

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/proofs/{proof_id}", headers=headers)

    def list_design_proofs(self, design_id, headers, params=None):
        return self._request("GET", f"/designs/{design_id}/proofs", headers=headers, params=params)

    def list_proofs(self, headers, params=None):
        return self._request("GET", "/proofs", headers=headers, params=params)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def add_line_item(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/line-items", payload, headers)

    def delete_line_item(self, order_id, line_item_id, headers):
        return self._request("DELETE", f"/orders/{order_id}/line-items/{line_item_id}", headers=headers)

    def apply_rush(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/apply-rush", payload, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", headers=headers)

    def pay_deposit(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay-deposit", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_order_line_items(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/line-items", headers=headers, params=params)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    # ---- Addressing jobs ----
    def create_addressing_job(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/addressing-jobs", payload, headers)

    def list_order_addressing_jobs(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/addressing-jobs", headers=headers, params=params)

    def get_addressing_job(self, addressing_job_id, headers):
        return self._request("GET", f"/addressing-jobs/{addressing_job_id}", headers=headers)

    # ---- Work orders ----
    def advance_production(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/production", payload, headers)

    def advance_addressing(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/addressing", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_order_work_orders(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/work-orders", headers=headers, params=params)

    # ---- Shipments ----
    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/dispatch", headers=headers)

    def mark_shipment_delivered(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/mark-delivered", headers=headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_order_shipments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/shipments", headers=headers, params=params)

    # ---- Test-driving endpoints ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/_payments/simulate", payload, headers)


api_client = ApiClient()
