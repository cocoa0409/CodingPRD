"""API client: one method per endpoint defined in the PRD (mounted under /merch)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Tour ---
    def create_tour(self, payload, headers):
        return self._request("POST", "/merch/tours", payload, headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/merch/tours", headers=headers, params=params)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/merch/tours/{tour_id}", headers=headers)

    def activate_tour(self, tour_id, headers):
        return self._request("POST", f"/merch/tours/{tour_id}/activate", {}, headers)

    def close_tour(self, tour_id, headers):
        return self._request("POST", f"/merch/tours/{tour_id}/close", {}, headers)

    def patch_royalty_config(self, tour_id, payload, headers):
        return self._request("PATCH", f"/merch/tours/{tour_id}/royalty-config", payload, headers)

    # --- Show ---
    def create_show(self, payload, headers):
        return self._request("POST", "/merch/shows", payload, headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/merch/shows", headers=headers, params=params)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/merch/shows/{show_id}", headers=headers)

    def open_show(self, show_id, headers):
        return self._request("POST", f"/merch/shows/{show_id}/open", {}, headers)

    def begin_reconciliation(self, show_id, headers):
        return self._request("POST", f"/merch/shows/{show_id}/begin-reconciliation", {}, headers)

    def cancel_show(self, show_id, headers):
        return self._request("POST", f"/merch/shows/{show_id}/cancel", {}, headers)

    def close_out_show(self, show_id, payload, headers):
        return self._request("POST", f"/merch/shows/{show_id}/close-out", payload, headers)

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/merch/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/merch/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/merch/products/{product_id}", headers=headers)

    # --- ShowProduct (price setting) ---
    def create_show_product(self, payload, headers):
        return self._request("POST", "/merch/show-products", payload, headers)

    def list_show_products(self, headers, params=None):
        return self._request("GET", "/merch/show-products", headers=headers, params=params)

    def get_show_product(self, show_product_id, headers):
        return self._request("GET", f"/merch/show-products/{show_product_id}", headers=headers)

    def reprice_show_product(self, show_product_id, payload, headers):
        return self._request("PATCH", f"/merch/show-products/{show_product_id}", payload, headers)

    # --- Allocation ---
    def generate_allocations(self, show_id, payload, headers):
        return self._request("POST", f"/merch/shows/{show_id}/allocations/generate", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/merch/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/merch/allocations/{allocation_id}", headers=headers)

    # --- Seller ---
    def create_seller(self, payload, headers):
        return self._request("POST", "/merch/sellers", payload, headers)

    def list_sellers(self, headers, params=None):
        return self._request("GET", "/merch/sellers", headers=headers, params=params)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/merch/sellers/{seller_id}", headers=headers)

    # --- SellerSession ---
    def create_seller_session(self, payload, headers):
        return self._request("POST", "/merch/seller-sessions", payload, headers)

    def list_seller_sessions(self, headers, params=None):
        return self._request("GET", "/merch/seller-sessions", headers=headers, params=params)

    def get_seller_session(self, session_id, headers):
        return self._request("GET", f"/merch/seller-sessions/{session_id}", headers=headers)

    def count_out_session(self, session_id, payload, headers):
        return self._request("POST", f"/merch/seller-sessions/{session_id}/count-out", payload, headers)

    def verify_session(self, session_id, payload, headers):
        return self._request("POST", f"/merch/seller-sessions/{session_id}/verify", payload, headers)

    # --- SaleRecord ---
    def create_sale_record(self, payload, headers):
        return self._request("POST", "/merch/sale-records", payload, headers)

    def list_sale_records(self, headers, params=None):
        return self._request("GET", "/merch/sale-records", headers=headers, params=params)

    def get_sale_record(self, sale_record_id, headers):
        return self._request("GET", f"/merch/sale-records/{sale_record_id}", headers=headers)

    def void_sale_record(self, sale_record_id, payload, headers):
        return self._request("POST", f"/merch/sale-records/{sale_record_id}/void", payload, headers)

    # --- OnlineOrder ---
    def create_online_order(self, payload, headers):
        return self._request("POST", "/merch/online-orders", payload, headers)

    def list_online_orders(self, headers, params=None):
        return self._request("GET", "/merch/online-orders", headers=headers, params=params)

    def get_online_order(self, order_id, headers):
        return self._request("GET", f"/merch/online-orders/{order_id}", headers=headers)

    def fulfill_online_order(self, order_id, headers):
        return self._request("POST", f"/merch/online-orders/{order_id}/fulfill", {}, headers)

    def cancel_online_order(self, order_id, headers):
        return self._request("POST", f"/merch/online-orders/{order_id}/cancel", {}, headers)

    # --- Settlement ---
    def list_settlements(self, headers, params=None):
        return self._request("GET", "/merch/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/merch/settlements/{settlement_id}", headers=headers)

    def reconcile_settlement(self, settlement_id, headers):
        return self._request("POST", f"/merch/settlements/{settlement_id}/reconcile", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/merch/settlements/{settlement_id}/dispute", payload, headers)

    def resolve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/merch/settlements/{settlement_id}/resolve", {}, headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/merch/settlements/{settlement_id}/finalize", {}, headers)

    def rebase_royalty(self, settlement_id, headers):
        return self._request("POST", f"/merch/settlements/{settlement_id}/rebase-royalty", {}, headers)

    # --- Shipment (restock & routing) ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/merch/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/merch/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/merch/shipments/{shipment_id}", headers=headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/merch/shipments/{shipment_id}/dispatch", {}, headers)

    def receive_shipment(self, shipment_id, headers):
        return self._request("POST", f"/merch/shipments/{shipment_id}/receive", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/merch/shipments/{shipment_id}/cancel", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/merch/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
