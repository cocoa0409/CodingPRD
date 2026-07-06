"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_product_bake_batches(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/bake-batches", headers=headers, params=params)

    # --- ProductionDay ---
    def create_production_day(self, payload, headers):
        return self._request("POST", "/production-days", payload, headers)

    def list_production_days(self, headers, params=None):
        return self._request("GET", "/production-days", headers=headers, params=params)

    def get_production_day(self, day_id, headers):
        return self._request("GET", f"/production-days/{day_id}", headers=headers)

    def start_baking(self, day_id, headers):
        return self._request("POST", f"/production-days/{day_id}/start-baking", {}, headers)

    def open_sales(self, day_id, headers):
        return self._request("POST", f"/production-days/{day_id}/open-sales", {}, headers)

    def close_cutoff(self, day_id, headers):
        return self._request("POST", f"/production-days/{day_id}/close-cutoff", {}, headers)

    def reconcile_day(self, day_id, payload, headers):
        return self._request("POST", f"/production-days/{day_id}/reconcile", payload, headers)

    # --- BakeBatch ---
    def create_bake_batch(self, day_id, payload, headers):
        return self._request("POST", f"/production-days/{day_id}/bake-batches", payload, headers)

    def list_bake_batches(self, day_id, headers, params=None):
        return self._request("GET", f"/production-days/{day_id}/bake-batches", headers=headers, params=params)

    def get_bake_batch(self, day_id, batch_id, headers):
        return self._request("GET", f"/production-days/{day_id}/bake-batches/{batch_id}", headers=headers)

    def bake_batch(self, day_id, batch_id, payload, headers):
        return self._request("POST", f"/production-days/{day_id}/bake-batches/{batch_id}/bake", payload, headers)

    def markdown_batch(self, day_id, batch_id, headers):
        return self._request("POST", f"/production-days/{day_id}/bake-batches/{batch_id}/markdown", {}, headers)

    def sweep_batch(self, day_id, batch_id, headers):
        return self._request("POST", f"/production-days/{day_id}/bake-batches/{batch_id}/sweep", {}, headers)

    # --- RetailOrder ---
    def create_retail_order(self, day_id, payload, headers):
        return self._request("POST", f"/production-days/{day_id}/retail-orders", payload, headers)

    def list_retail_orders(self, day_id, headers, params=None):
        return self._request("GET", f"/production-days/{day_id}/retail-orders", headers=headers, params=params)

    def get_retail_order(self, day_id, order_id, headers):
        return self._request("GET", f"/production-days/{day_id}/retail-orders/{order_id}", headers=headers)

    def pay_retail_order(self, day_id, order_id, headers):
        return self._request("POST", f"/production-days/{day_id}/retail-orders/{order_id}/pay", {}, headers)

    def void_retail_order(self, day_id, order_id, headers):
        return self._request("POST", f"/production-days/{day_id}/retail-orders/{order_id}/void", {}, headers)

    def refund_retail_order(self, day_id, order_id, headers):
        return self._request("POST", f"/production-days/{day_id}/retail-orders/{order_id}/refund", {}, headers)

    # --- LoyaltyAccount ---
    def create_loyalty_account(self, payload, headers):
        return self._request("POST", "/loyalty-accounts", payload, headers)

    def get_loyalty_account(self, account_id, headers):
        return self._request("GET", f"/loyalty-accounts/{account_id}", headers=headers)

    def list_loyalty_retail_orders(self, account_id, headers, params=None):
        return self._request("GET", f"/loyalty-accounts/{account_id}/retail-orders", headers=headers, params=params)

    # --- WholesaleAccount ---
    def create_wholesale_account(self, payload, headers):
        return self._request("POST", "/wholesale-accounts", payload, headers)

    def get_wholesale_account(self, account_id, headers):
        return self._request("GET", f"/wholesale-accounts/{account_id}", headers=headers)

    def list_account_deliveries(self, account_id, headers, params=None):
        return self._request("GET", f"/wholesale-accounts/{account_id}/wholesale-deliveries", headers=headers, params=params)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/wholesale-accounts/{account_id}/suspend", {}, headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"/wholesale-accounts/{account_id}/reactivate", {}, headers)

    def record_payment(self, account_id, payload, headers):
        return self._request("POST", f"/wholesale-accounts/{account_id}/payments", payload, headers)

    # --- StandingOrder ---
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/standing-orders", payload, headers)

    def list_standing_orders(self, headers, params=None):
        return self._request("GET", "/standing-orders", headers=headers, params=params)

    def get_standing_order(self, so_id, headers):
        return self._request("GET", f"/standing-orders/{so_id}", headers=headers)

    def list_standing_order_deliveries(self, so_id, headers, params=None):
        return self._request("GET", f"/standing-orders/{so_id}/wholesale-deliveries", headers=headers, params=params)

    def pause_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/pause", {}, headers)

    def resume_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/resume", {}, headers)

    # --- WholesaleDelivery ---
    def create_wholesale_delivery(self, day_id, payload, headers):
        return self._request("POST", f"/production-days/{day_id}/wholesale-deliveries", payload, headers)

    def list_wholesale_deliveries(self, day_id, headers, params=None):
        return self._request("GET", f"/production-days/{day_id}/wholesale-deliveries", headers=headers, params=params)

    def get_wholesale_delivery(self, day_id, delivery_id, headers):
        return self._request("GET", f"/production-days/{day_id}/wholesale-deliveries/{delivery_id}", headers=headers)

    def pick_delivery(self, day_id, delivery_id, headers):
        return self._request("POST", f"/production-days/{day_id}/wholesale-deliveries/{delivery_id}/pick", {}, headers)

    def deliver_delivery(self, day_id, delivery_id, headers):
        return self._request("POST", f"/production-days/{day_id}/wholesale-deliveries/{delivery_id}/deliver", {}, headers)

    def invoice_delivery(self, day_id, delivery_id, headers):
        return self._request("POST", f"/production-days/{day_id}/wholesale-deliveries/{delivery_id}/invoice", {}, headers)

    def cancel_delivery(self, day_id, delivery_id, headers):
        return self._request("POST", f"/production-days/{day_id}/wholesale-deliveries/{delivery_id}/cancel", {}, headers)

    # --- PreOrder ---
    def create_pre_order(self, payload, headers):
        return self._request("POST", "/pre-orders", payload, headers)

    def list_pre_orders(self, headers, params=None):
        return self._request("GET", "/pre-orders", headers=headers, params=params)

    def get_pre_order(self, pre_order_id, headers):
        return self._request("GET", f"/pre-orders/{pre_order_id}", headers=headers)

    def record_deposit(self, pre_order_id, payload, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/deposit", payload, headers)

    def confirm_pre_order(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/confirm", {}, headers)

    def fulfill_pre_order(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/fulfill", {}, headers)

    def cancel_pre_order(self, pre_order_id, headers):
        return self._request("POST", f"/pre-orders/{pre_order_id}/cancel", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
