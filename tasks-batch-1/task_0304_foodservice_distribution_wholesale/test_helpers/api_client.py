"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Distributor ───────────────────────────────────────────────────────
    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/distributors/{distributor_id}", headers=headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Warehouse ─────────────────────────────────────────────────────────
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}", headers=headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", "/warehouses", headers=headers, params=params)

    # ─── Route ─────────────────────────────────────────────────────────────
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    # ─── Product / catalog ─────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", headers=headers)

    # ─── PriceTier ─────────────────────────────────────────────────────────
    def create_price_tier(self, payload, headers):
        return self._request("POST", "/price-tiers", payload, headers)

    def get_price_tier(self, price_tier_id, headers):
        return self._request("GET", f"/price-tiers/{price_tier_id}", headers=headers)

    def list_price_tiers(self, headers, params=None):
        return self._request("GET", "/price-tiers", headers=headers, params=params)

    # ─── InventoryLot ──────────────────────────────────────────────────────
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    # ─── Customer ──────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def adjust_credit_limit(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-limit", payload, headers)

    def credit_hold(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-hold", headers=headers)

    def credit_release(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/credit-release", headers=headers)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/close", headers=headers)

    # ─── OrderGuide ────────────────────────────────────────────────────────
    def create_order_guide(self, payload, headers):
        return self._request("POST", "/order-guides", payload, headers)

    def get_order_guide(self, order_guide_id, headers):
        return self._request("GET", f"/order-guides/{order_guide_id}", headers=headers)

    def list_order_guides(self, headers, params=None):
        return self._request("GET", "/order-guides", headers=headers, params=params)

    def get_replenishment(self, order_guide_id, headers):
        return self._request("GET", f"/order-guides/{order_guide_id}/replenishment", headers=headers)

    # ─── OrderGuideItem ────────────────────────────────────────────────────
    def create_order_guide_item(self, payload, headers):
        return self._request("POST", "/order-guide-items", payload, headers)

    def get_order_guide_item(self, order_guide_item_id, headers):
        return self._request("GET", f"/order-guide-items/{order_guide_item_id}", headers=headers)

    def list_order_guide_items(self, headers, params=None):
        return self._request("GET", "/order-guide-items", headers=headers, params=params)

    # ─── Order ─────────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def remove_order_line(self, order_line_id, headers):
        return self._request("POST", f"/order-lines/{order_line_id}/remove", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", headers=headers)

    def approve_credit(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/approve-credit", payload, headers)

    def start_pick(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/start-pick", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", headers=headers)

    # ─── Shipment ──────────────────────────────────────────────────────────
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def load_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/load", headers=headers)

    def pod_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/pod", payload, headers)

    # ─── Return ────────────────────────────────────────────────────────────
    def create_return(self, payload, headers):
        return self._request("POST", "/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/approve", headers=headers)

    def reject_return(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/reject", headers=headers)

    def issue_credit(self, return_id, headers):
        return self._request("POST", f"/returns/{return_id}/issue-credit", headers=headers)


api_client = ApiClient()
