"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Member ------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_member_store_credit_entries(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/store-credit-entries",
            headers=headers, params=params,
        )

    def list_member_sales(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/sales", headers=headers, params=params,
        )

    def adjust_store_credit(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/store-credit/adjustments", payload, headers,
        )

    # --- Product -----------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_stocks(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/products/{product_id}/stocks", headers=headers, params=params,
        )

    def list_product_inventory_items(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/products/{product_id}/inventory-items",
            headers=headers, params=params,
        )

    # --- ProductStock ------------------------------------------------------
    def create_product_stock(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/stocks", payload, headers)

    def get_product_stock(self, stock_id, headers):
        return self._request("GET", f"/product-stocks/{stock_id}", headers=headers)

    def release_product_stock(self, stock_id, headers):
        return self._request(
            "POST", f"/product-stocks/{stock_id}/release", headers=headers,
        )

    def list_product_stock_allocations(self, stock_id, headers, params=None):
        return self._request(
            "GET", f"/product-stocks/{stock_id}/allocations",
            headers=headers, params=params,
        )

    # --- InventoryItem -----------------------------------------------------
    def create_inventory_item(self, product_id, payload, headers):
        return self._request(
            "POST", f"/products/{product_id}/inventory-items", payload, headers,
        )

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    # --- PreOrder ----------------------------------------------------------
    def create_pre_order(self, payload, headers):
        return self._request("POST", "/pre-orders", payload, headers)

    def get_pre_order(self, pre_order_id, headers):
        return self._request("GET", f"/pre-orders/{pre_order_id}", headers=headers)

    def list_pre_orders(self, headers, params=None):
        return self._request("GET", "/pre-orders", headers=headers, params=params)

    def list_pre_order_allocations(self, pre_order_id, headers, params=None):
        return self._request(
            "GET", f"/pre-orders/{pre_order_id}/allocations",
            headers=headers, params=params,
        )

    def pay_pre_order(self, pre_order_id, payload, headers):
        return self._request(
            "POST", f"/pre-orders/{pre_order_id}/payments", payload, headers,
        )

    def fulfill_pre_order(self, pre_order_id, headers):
        return self._request(
            "POST", f"/pre-orders/{pre_order_id}/fulfill", headers=headers,
        )

    def cancel_pre_order(self, pre_order_id, headers):
        return self._request(
            "POST", f"/pre-orders/{pre_order_id}/cancel", headers=headers,
        )

    # --- TradeIn -----------------------------------------------------------
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/trade-ins", headers=headers, params=params)

    def grade_trade_in(self, trade_in_id, payload, headers):
        return self._request(
            "POST", f"/trade-ins/{trade_in_id}/grade", payload, headers,
        )

    def dispute_trade_in(self, trade_in_id, headers):
        return self._request(
            "POST", f"/trade-ins/{trade_in_id}/dispute", headers=headers,
        )

    def accept_trade_in(self, trade_in_id, headers):
        return self._request(
            "POST", f"/trade-ins/{trade_in_id}/accept", headers=headers,
        )

    def void_trade_in(self, trade_in_id, headers):
        return self._request(
            "POST", f"/trade-ins/{trade_in_id}/void", headers=headers,
        )

    # --- Rental ------------------------------------------------------------
    def create_rental(self, payload, headers):
        return self._request("POST", "/rentals", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/rentals/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/rentals", headers=headers, params=params)

    def checkout_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/checkout", headers=headers,
        )

    def return_rental(self, rental_id, headers):
        return self._request(
            "POST", f"/rentals/{rental_id}/return", headers=headers,
        )

    # --- Sale --------------------------------------------------------------
    def create_sale(self, payload, headers):
        return self._request("POST", "/sales", payload, headers)

    # --- Station -----------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    # --- Tournament --------------------------------------------------------
    def create_tournament(self, payload, headers):
        return self._request("POST", "/tournaments", payload, headers)

    def get_tournament(self, tournament_id, headers):
        return self._request("GET", f"/tournaments/{tournament_id}", headers=headers)

    def list_tournaments(self, headers, params=None):
        return self._request("GET", "/tournaments", headers=headers, params=params)

    def register_tournament(self, tournament_id, payload, headers):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/register", payload, headers,
        )


api_client = ApiClient()
