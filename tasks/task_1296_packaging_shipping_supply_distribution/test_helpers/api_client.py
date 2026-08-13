"""API client: one method per endpoint defined in the PRD (section 4).

All endpoints are mounted under the /packaging-distribution prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/packaging-distribution"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def patch_account(self, account_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/accounts/{account_id}", payload, headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/suspend", {}, headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"{PREFIX}/accounts/{account_id}/reactivate", {}, headers)

    # --- Products and quantity breaks ---
    def create_product(self, payload, headers):
        return self._request("POST", f"{PREFIX}/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}", headers=headers)

    def update_product(self, product_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/products/{product_id}", payload, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"{PREFIX}/products/{product_id}/discontinue", {}, headers)

    def create_quantity_break(self, product_id, payload, headers):
        return self._request("POST", f"{PREFIX}/products/{product_id}/quantity-breaks", payload, headers)

    def list_quantity_breaks(self, product_id, headers):
        return self._request("GET", f"{PREFIX}/products/{product_id}/quantity-breaks", headers=headers)

    def delete_quantity_break(self, break_id, headers):
        return self._request("DELETE", f"{PREFIX}/quantity-breaks/{break_id}", headers=headers)

    # --- Warehouses ---
    def create_warehouse(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warehouses", payload, headers)

    def list_warehouses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warehouses", headers=headers, params=params)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"{PREFIX}/warehouses/{warehouse_id}", headers=headers)

    def deactivate_warehouse(self, warehouse_id, headers):
        return self._request("POST", f"{PREFIX}/warehouses/{warehouse_id}/deactivate", {}, headers)

    def activate_warehouse(self, warehouse_id, headers):
        return self._request("POST", f"{PREFIX}/warehouses/{warehouse_id}/activate", {}, headers)

    # --- Inventory ---
    def create_inventory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inventory", payload, headers)

    def list_inventory(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inventory", headers=headers, params=params)

    def get_inventory(self, inventory_id, headers):
        return self._request("GET", f"{PREFIX}/inventory/{inventory_id}", headers=headers)

    def receive_inventory(self, inventory_id, payload, headers):
        return self._request("POST", f"{PREFIX}/inventory/{inventory_id}/receive", payload, headers)

    def adjust_inventory(self, inventory_id, payload, headers):
        return self._request("POST", f"{PREFIX}/inventory/{inventory_id}/adjust", payload, headers)

    # --- Orders and order lines ---
    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/lines", payload, headers)

    def list_order_lines(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}/lines", headers=headers)

    def list_order_lines_flat(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/order-lines/{line_id}", headers=headers)

    def update_order_line(self, order_id, line_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/orders/{order_id}/lines/{line_id}", payload, headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/submit", {}, headers)

    def approve_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/approve", {}, headers)

    def reject_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/reject", payload, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/ship", {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/cancel", payload, headers)

    def pay_invoice(self, order_id, headers):
        return self._request("POST", f"{PREFIX}/orders/{order_id}/invoice/pay", {}, headers)

    # --- Custom print jobs ---
    def list_custom_print_jobs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/custom-print-jobs", headers=headers, params=params)

    def get_custom_print_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/custom-print-jobs/{job_id}", headers=headers)

    def start_custom_print_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/custom-print-jobs/{job_id}/start", {}, headers)

    def advance_custom_print_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/custom-print-jobs/{job_id}/advance", {}, headers)

    def receive_custom_print_job(self, job_id, payload, headers):
        return self._request("POST", f"{PREFIX}/custom-print-jobs/{job_id}/receive", payload, headers)

    # --- Returns ---
    def create_return(self, payload, headers):
        return self._request("POST", f"{PREFIX}/returns", payload, headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/returns", headers=headers, params=params)

    def get_return(self, return_id, headers):
        return self._request("GET", f"{PREFIX}/returns/{return_id}", headers=headers)

    def list_return_lines(self, return_id, headers):
        return self._request("GET", f"{PREFIX}/returns/{return_id}/lines", headers=headers)

    def list_return_lines_flat(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/return-lines", headers=headers, params=params)

    def get_return_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/return-lines/{line_id}", headers=headers)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"{PREFIX}/returns/{return_id}/approve", {}, headers)

    def reject_return(self, return_id, payload, headers):
        return self._request("POST", f"{PREFIX}/returns/{return_id}/reject", payload, headers)

    def receive_return(self, return_id, headers):
        return self._request("POST", f"{PREFIX}/returns/{return_id}/receive", {}, headers)

    def restock_return(self, return_id, headers):
        return self._request("POST", f"{PREFIX}/returns/{return_id}/restock", {}, headers)

    # --- Restock notifications ---
    def create_restock_notification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/restock-notifications", payload, headers)

    def list_restock_notifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/restock-notifications", headers=headers, params=params)

    def get_restock_notification(self, notification_id, headers):
        return self._request("GET", f"{PREFIX}/restock-notifications/{notification_id}", headers=headers)

    def cancel_restock_notification(self, notification_id, headers):
        return self._request("POST", f"{PREFIX}/restock-notifications/{notification_id}/cancel", {}, headers)


api_client = ApiClient()
