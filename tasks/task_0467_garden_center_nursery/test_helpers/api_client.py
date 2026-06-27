"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Nursery ---
    def create_nursery(self, payload, headers):
        return self._request("POST", "/nurseries", payload, headers)

    def get_nursery(self, nursery_id, headers):
        return self._request("GET", f"/nurseries/{nursery_id}", headers=headers)

    # --- Account ---
    def create_account(self, nursery_id, payload, headers):
        return self._request(
            "POST", f"/nurseries/{nursery_id}/accounts", payload, headers
        )

    def list_accounts(self, nursery_id, headers, params=None):
        return self._request(
            "GET", f"/nurseries/{nursery_id}/accounts", headers=headers, params=params
        )

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_loyalty_events(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/loyalty-events", headers=headers, params=params
        )

    def list_account_orders(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/orders", headers=headers, params=params
        )

    def list_account_special_orders(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/special-orders", headers=headers, params=params
        )

    # --- Product ---
    def create_product(self, nursery_id, payload, headers):
        return self._request(
            "POST", f"/nurseries/{nursery_id}/products", payload, headers
        )

    def list_products(self, nursery_id, headers, params=None):
        return self._request(
            "GET", f"/nurseries/{nursery_id}/products", headers=headers, params=params
        )

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_inventory_lots(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/products/{product_id}/inventory-lots", headers=headers, params=params
        )

    # --- InventoryLot ---
    def create_inventory_lot(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/inventory-lots", payload, headers
        )

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def release_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/release", {}, headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/quarantine", {}, headers)

    def create_care_log(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/inventory-lots/{lot_id}/care-log", payload, headers
        )

    def list_care_log(self, lot_id, headers, params=None):
        return self._request(
            "GET", f"/inventory-lots/{lot_id}/care-log", headers=headers, params=params
        )

    # --- SeasonalPromotion ---
    def create_promotion(self, nursery_id, payload, headers):
        return self._request(
            "POST", f"/nurseries/{nursery_id}/promotions", payload, headers
        )

    def list_promotions(self, nursery_id, headers, params=None):
        return self._request(
            "GET", f"/nurseries/{nursery_id}/promotions", headers=headers, params=params
        )

    def activate_promotion(self, promotion_id, headers):
        return self._request(
            "POST", f"/promotions/{promotion_id}/activate", {}, headers
        )

    # --- Vehicle ---
    def create_vehicle(self, nursery_id, payload, headers):
        return self._request(
            "POST", f"/nurseries/{nursery_id}/vehicles", payload, headers
        )

    def list_vehicles(self, nursery_id, headers, params=None):
        return self._request(
            "GET", f"/nurseries/{nursery_id}/vehicles", headers=headers, params=params
        )

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicle_deliveries(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}/deliveries", headers=headers, params=params
        )

    # --- Order ---
    def create_order(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/orders", {}, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def list_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/lines", headers=headers, params=params
        )

    def list_order_loyalty_events(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/loyalty-events", headers=headers, params=params
        )

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/confirm", payload, headers)

    def allocate_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/allocate", payload, headers)

    def charge_account(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/charge-account", payload, headers
        )

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def fulfill_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    # --- SpecialOrder ---
    def create_special_order(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/special-orders", payload, headers
        )

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, so_id, headers):
        return self._request("GET", f"/special-orders/{so_id}", headers=headers)

    def list_special_order_inventory_lots(self, so_id, headers, params=None):
        return self._request(
            "GET", f"/special-orders/{so_id}/inventory-lots", headers=headers, params=params
        )

    def approve_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/approve", {}, headers)

    def receive_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/receive", {}, headers)

    def cancel_special_order(self, so_id, headers):
        return self._request("POST", f"/special-orders/{so_id}/cancel", {}, headers)

    # --- Delivery ---
    def create_delivery(self, order_id, payload, headers):
        return self._request(
            "POST", f"/orders/{order_id}/deliveries", payload, headers
        )

    def list_order_deliveries(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/deliveries", headers=headers, params=params
        )

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def dispatch_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/dispatch", {}, headers
        )

    def complete_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/complete", {}, headers
        )

    def cancel_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/deliveries/{delivery_id}/cancel", {}, headers
        )

    # --- WarrantyClaim ---
    def create_warranty_claim(self, line_id, payload, headers):
        return self._request(
            "POST", f"/order-lines/{line_id}/warranty-claims", payload, headers
        )

    def list_warranty_claims(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/order-lines/{line_id}/warranty-claims", headers=headers, params=params
        )

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/approve", {}, headers
        )

    def deny_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/deny", {}, headers
        )


api_client = ApiClient()
