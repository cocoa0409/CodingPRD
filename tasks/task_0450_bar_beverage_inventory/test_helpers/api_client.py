"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def archive_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/archive", headers=headers)

    def keg_yield(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/keg-yield", headers=headers, params=params)

    def reorder_suggestion(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/reorder-suggestion", headers=headers, params=params)

    # ---- Product sub-resource listings ----
    def list_product_par_settings(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/par-settings", headers=headers, params=params)

    def list_product_recipe_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/recipe-lines", headers=headers, params=params)

    def list_product_count_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/count-lines", headers=headers, params=params)

    def list_product_po_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/po-lines", headers=headers, params=params)

    def list_product_invoice_lines(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/invoice-lines", headers=headers, params=params)

    def list_product_waste_logs(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/waste-logs", headers=headers, params=params)

    def list_product_keg_taps(self, product_id, headers, params=None):
        return self._request("GET", f"/products/{product_id}/keg-taps", headers=headers, params=params)

    # ---- Par settings ----
    def create_par_setting(self, payload, headers):
        return self._request("POST", "/par-settings", payload, headers)

    def list_par_settings(self, headers, params=None):
        return self._request("GET", "/par-settings", headers=headers, params=params)

    # ---- Recipes ----
    def create_recipe(self, payload, headers):
        return self._request("POST", "/recipes", payload, headers)

    def get_recipe(self, recipe_id, headers):
        return self._request("GET", f"/recipes/{recipe_id}", headers=headers)

    def add_recipe_line(self, recipe_id, payload, headers):
        return self._request("POST", f"/recipes/{recipe_id}/lines", payload, headers)

    def list_recipe_lines(self, recipe_id, headers, params=None):
        return self._request("GET", f"/recipes/{recipe_id}/lines", headers=headers, params=params)

    def publish_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/publish", headers=headers)

    def revise_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/revise", headers=headers)

    def retire_recipe(self, recipe_id, headers):
        return self._request("POST", f"/recipes/{recipe_id}/retire", headers=headers)

    # ---- Menu items ----
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def record_sales(self, menu_item_id, payload, headers):
        return self._request("POST", f"/menu-items/{menu_item_id}/record-sales", payload, headers)

    def delist_menu_item(self, menu_item_id, headers):
        return self._request("POST", f"/menu-items/{menu_item_id}/delist", headers=headers)

    def menu_engineering(self, headers, params=None):
        return self._request("GET", "/menu-items/engineering", headers=headers, params=params)

    # ---- Count sessions ----
    def create_count_session(self, payload, headers):
        return self._request("POST", "/count-sessions", payload, headers)

    def get_count_session(self, count_session_id, headers):
        return self._request("GET", f"/count-sessions/{count_session_id}", headers=headers)

    def add_count_line(self, count_session_id, payload, headers):
        return self._request("POST", f"/count-sessions/{count_session_id}/count-lines", payload, headers)

    def list_count_lines(self, count_session_id, headers, params=None):
        return self._request("GET", f"/count-sessions/{count_session_id}/count-lines", headers=headers, params=params)

    def finalize_count_session(self, count_session_id, payload, headers):
        return self._request("POST", f"/count-sessions/{count_session_id}/finalize", payload, headers)

    def void_count_session(self, count_session_id, payload, headers):
        return self._request("POST", f"/count-sessions/{count_session_id}/void", payload, headers)

    # ---- Purchase orders ----
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def add_po_line(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/lines", payload, headers)

    def list_po_lines(self, po_id, headers, params=None):
        return self._request("GET", f"/purchase-orders/{po_id}/lines", headers=headers, params=params)

    def submit_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/submit", headers=headers)

    def close_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/close", headers=headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", headers=headers)

    # ---- Invoices ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def add_invoice_line(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/lines", payload, headers)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/lines", headers=headers, params=params)

    def post_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/post", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", headers=headers)

    # ---- Waste logs ----
    def create_waste_log(self, payload, headers):
        return self._request("POST", "/waste-logs", payload, headers)

    def list_waste_logs(self, headers, params=None):
        return self._request("GET", "/waste-logs", headers=headers, params=params)

    # ---- Keg taps ----
    def create_keg_tap(self, payload, headers):
        return self._request("POST", "/keg-taps", payload, headers)

    def list_keg_taps(self, headers, params=None):
        return self._request("GET", "/keg-taps", headers=headers, params=params)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
