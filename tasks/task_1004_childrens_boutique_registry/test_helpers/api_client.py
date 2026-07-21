"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Stores ----
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- SKUs ----
    def create_sku(self, payload, headers):
        return self._request("POST", "/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/skus", headers=headers, params=params)

    def restock_sku(self, sku_id, payload, headers):
        return self._request("POST", f"/skus/{sku_id}/restock", payload, headers)

    # ---- Registries ----
    def create_registry(self, payload, headers):
        return self._request("POST", "/registries", payload, headers)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"/registries/{registry_id}", headers=headers)

    def list_registries(self, headers, params=None):
        return self._request("GET", "/registries", headers=headers, params=params)

    def activate_registry(self, registry_id, headers, payload=None):
        return self._request("POST", f"/registries/{registry_id}/activate", payload or {}, headers)

    def archive_registry(self, registry_id, headers, payload=None):
        return self._request("POST", f"/registries/{registry_id}/archive", payload or {}, headers)

    def add_registry_item(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/items", payload, headers)

    def get_registry_item(self, item_id, headers):
        return self._request("GET", f"/registry-items/{item_id}", headers=headers)

    def list_registry_items(self, headers, params=None):
        return self._request("GET", "/registry-items", headers=headers, params=params)

    # ---- Registry Gifts ----
    def create_gift(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/gifts", payload, headers)

    def get_registry_gift(self, gift_id, headers):
        return self._request("GET", f"/registry-gifts/{gift_id}", headers=headers)

    def list_registry_gifts(self, headers, params=None):
        return self._request("GET", "/registry-gifts", headers=headers, params=params)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/pay", payload, headers)

    def mark_ready_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/mark-ready", payload or {}, headers)

    def complete_pickup_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/complete-pickup", payload or {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/cancel", payload or {}, headers)

    # ---- Consignment Shelves ----
    def create_shelf(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/consignment-shelves", payload, headers)

    def get_shelf(self, shelf_id, headers):
        return self._request("GET", f"/consignment-shelves/{shelf_id}", headers=headers)

    def list_shelves(self, headers, params=None):
        return self._request("GET", "/consignment-shelves", headers=headers, params=params)

    def close_shelf(self, shelf_id, headers, payload=None):
        return self._request("POST", f"/consignment-shelves/{shelf_id}/close", payload or {}, headers)

    # ---- Consignment Items ----
    def create_consignment_item(self, payload, headers):
        return self._request("POST", "/consignment-items", payload, headers)

    def get_consignment_item(self, item_id, headers):
        return self._request("GET", f"/consignment-items/{item_id}", headers=headers)

    def list_consignment_items(self, headers, params=None):
        return self._request("GET", "/consignment-items", headers=headers, params=params)

    def display_consignment_item(self, item_id, payload, headers):
        return self._request("POST", f"/consignment-items/{item_id}/display", payload, headers)

    def sell_consignment_item(self, item_id, payload, headers):
        return self._request("POST", f"/consignment-items/{item_id}/sell", payload, headers)

    # ---- Trade-Ins ----
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def accept_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/trade-ins/{trade_in_id}/accept", payload or {}, headers)

    def reject_trade_in(self, trade_in_id, headers, payload=None):
        return self._request("POST", f"/trade-ins/{trade_in_id}/reject", payload or {}, headers)

    # ---- Special Orders ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, so_id, headers):
        return self._request("GET", f"/special-orders/{so_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def fulfill_special_order(self, so_id, headers, payload=None):
        return self._request("POST", f"/special-orders/{so_id}/fulfill", payload or {}, headers)

    def cancel_special_order(self, so_id, headers, payload=None):
        return self._request("POST", f"/special-orders/{so_id}/cancel", payload or {}, headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
