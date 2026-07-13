"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Supplier ----
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    # ---- Product & PriceTier ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def create_price_tier(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/price-tiers", payload, headers)

    def list_price_tiers(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/price-tiers", headers=headers, params=params)

    # ---- DecorationStation ----
    def create_station(self, payload, headers):
        return self._request("POST", "/decoration-stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/decoration-stations/{station_id}", headers=headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def create_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def quote_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/quote", {}, headers)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", {}, headers)

    def start_production(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/start-production", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    def create_payment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/payments", payload, headers)

    def reorder(self, source_order_id, payload, headers):
        return self._request("POST", f"/orders/{source_order_id}/reorder", payload, headers)

    # ---- OrderLine ----
    def get_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def schedule_line(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/schedule", payload, headers)

    def start_print(self, line_id, headers):
        return self._request("POST", f"/order-lines/{line_id}/start-print", {}, headers)

    def complete_run(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/complete-run", payload, headers)

    def qc_line(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/qc", payload, headers)

    # ---- ArtProof ----
    def create_art_proof(self, line_id, payload, headers):
        return self._request("POST", f"/order-lines/{line_id}/art-proofs", payload, headers)

    def list_art_proofs(self, line_id, headers, params=None):
        return self._request("GET", f"/order-lines/{line_id}/art-proofs", headers=headers, params=params)

    def get_art_proof(self, proof_id, headers):
        return self._request("GET", f"/art-proofs/{proof_id}", headers=headers)

    def submit_proof(self, proof_id, headers):
        return self._request("POST", f"/art-proofs/{proof_id}/submit", {}, headers)

    def approve_proof(self, proof_id, headers):
        return self._request("POST", f"/art-proofs/{proof_id}/approve", {}, headers)

    def request_changes(self, proof_id, payload, headers):
        return self._request("POST", f"/art-proofs/{proof_id}/request-changes", payload, headers)

    # ---- PurchaseOrder ----
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def issue_po(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/issue", {}, headers)

    def receive_po(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/receive", payload, headers)

    def cancel_po(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", {}, headers)

    # ---- Shipment ----
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)


api_client = ApiClient()
